"""Odoo instance lifecycle on Docker: deploy, copy, rename, backup and restore."""
import docker
import os
import git
from django.conf import settings
from ..models import Instance

ODOO_DATA_DIR = '/var/lib/odoo'


def host_path(path):
    """
    Translate a path inside this app's container into the path the Docker daemon sees.
    The project is mounted at BASE_DIR; HOST_WORKDIR is where it lives on the host.
    """
    path = str(path)
    base = str(settings.BASE_DIR)
    host_workdir = os.environ.get('HOST_WORKDIR', '').rstrip('/')
    if host_workdir and (path == base or path.startswith(base + os.sep)):
        return host_workdir + path[len(base):]
    return path


def odoo_config_target(odoo_version):
    # Every official image (10.0 included) reads ODOO_RC=/etc/odoo/odoo.conf
    return '/etc/odoo/odoo.conf'


PANEL_ADDONS_DIR = '/mnt/community-sh-addons'


def admin_login_secret(instance):
    """Key the panel and the instance's community_sh_login module share to sign admin links."""
    import hashlib
    return hashlib.sha256(f'community-sh-login:{instance.master_password}'.encode()).hexdigest()



def read_backup_metadata(path):
    """
    Describe a backup file. Formats: the panel's ZIP (database.dump + metadata.json), Odoo's own
    database-manager ZIP (dump.sql + filestore/ + manifest.json) and a bare pg_dump custom file.
    Returns {'format', 'database_name', 'odoo_version', 'has_filestore'}.
    """
    import json
    import zipfile
    if not zipfile.is_zipfile(path):
        with open(path, 'rb') as f:
            if f.read(5) != b'PGDMP':
                raise Exception('Formato no reconocido: sube un ZIP del panel, un ZIP de Odoo o un .dump de PostgreSQL')
        return {'format': 'pg_dump', 'database_name': None, 'odoo_version': None, 'has_filestore': False}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        has_filestore = any(n.startswith('filestore/') and not n.endswith('/') for n in names)
        if 'database.dump' in names:
            metadata = json.loads(zf.read('metadata.json')) if 'metadata.json' in names else {}
            return {'format': 'panel', 'database_name': metadata.get('database_name'),
                    'odoo_version': metadata.get('odoo_version'), 'has_filestore': has_filestore}
        if 'dump.sql' in names:
            manifest = json.loads(zf.read('manifest.json')) if 'manifest.json' in names else {}
            version = str(manifest.get('version') or manifest.get('version_info', [''])[0] or '')
            major = version.split('.')[0] if version else ''
            return {'format': 'odoo', 'database_name': manifest.get('db_name'),
                    'odoo_version': f'{major}.0' if major.isdigit() else None, 'has_filestore': has_filestore}
    raise Exception('El ZIP no contiene database.dump (backup del panel) ni dump.sql (backup de Odoo)')


def postgres_image(odoo_version):
    """PostgreSQL release each Odoo version supports (Odoo 20 needs 16+, Odoo 10-11 predate 12)."""
    major = int(float(odoo_version))
    if major <= 11:
        return 'postgres:10'
    if major <= 13:
        return 'postgres:12'
    if major <= 15:
        return 'postgres:13'
    if major <= 17:
        return 'postgres:15'
    return 'postgres:16'


class DockerService:
    def __init__(self):
        self.client = docker.from_env()
        # Remarks from the last deploy, shown in the task result
        self.deploy_notes = []

    def _get_container(self, name):
        try:
            return self.client.containers.get(name)
        except docker.errors.NotFound:
            return None

    def _resolve_data_volume(self, instance, container=None):
        """
        Volume holding /var/lib/odoo (filestore, sessions). Reuse the one the current
        container already uses (older deployments got an anonymous volume) so that
        redeploying never starts with an empty filestore.
        """
        if container is not None:
            for mount in container.attrs.get('Mounts', []):
                if mount.get('Destination') == ODOO_DATA_DIR and mount.get('Name'):
                    return mount['Name']
        return instance.data_volume or f"odoo_data_{instance.name}"

    def _write_odoo_config(self, instance, workspace_path, extra_repos=()):
        """
        Write the config into its own folder, mounted at /etc/odoo. Mounting a folder instead of
        a single file avoids Docker Desktop creating a directory when the file isn't synced yet.
        """
        config_dir = os.path.join(workspace_path, 'conf')
        os.makedirs(config_dir, exist_ok=True)
        addons_paths = ['/mnt/extra-addons'] + [f'/mnt/repos/{slug}' for slug in extra_repos]
        # community_sh_login: one-time admin links from the panel (loaded without installing it)
        addons_paths.append(PANEL_ADDONS_DIR)
        # Odoo 10 also loads web_kanban server-wide by default
        server_wide = 'base,web,web_kanban' if int(float(instance.odoo_version)) == 10 else 'base,web'
        panel_login = (f"server_wide_modules = {server_wide},community_sh_login\n"
                       f"community_sh_secret = {admin_login_secret(instance)}\n")
        content = (
            "[options]\n"
            f"addons_path = {','.join(addons_paths)}\n"
            f"data_dir = {ODOO_DATA_DIR}\n"
            f"admin_passwd = {instance.master_password}\n"
            # In the config (not only entrypoint args) so `odoo` run via exec can connect too
            f"db_host = db_{instance.name}\n"
            "db_port = 5432\n"
            "db_user = odoo\n"
            "db_password = odoo\n"
            # Odoo 20 listens on 127.0.0.1 by default; Odoo 10 calls the option xmlrpc_interface
            "http_interface = 0.0.0.0\n"
            "xmlrpc_interface = 0.0.0.0\n"
            # Behind Traefik: trust X-Forwarded-* so Odoo builds https:// URLs
            "proxy_mode = True\n"
            + panel_login
        )
        config_path = os.path.join(config_dir, os.path.basename(odoo_config_target(instance.odoo_version)))
        with open(config_path, 'w') as f:
            f.write(content)
        os.chmod(config_path, 0o644)
        # Earlier builds wrote openerp-server.conf for Odoo 10, which the image never reads
        stale = os.path.join(config_dir, 'openerp-server.conf')
        if os.path.exists(stale):
            os.remove(stale)
        # Older deployments mounted <workspace>/odoo.conf as a file
        legacy = os.path.join(workspace_path, 'odoo.conf')
        if os.path.isfile(legacy):
            os.remove(legacy)
        return config_dir

    def _github_token(self, instance):
        from ..config_models import GitHubConfig
        config = GitHubConfig.objects.filter(user=instance.owner).first() if instance.owner_id else None
        return config.personal_access_token if config and config.personal_access_token else ''

    def _sync_extra_repos(self, instance, workspace_path):
        """Clone or update the instance's extra repositories into <workspace>/repos/<slug>."""
        import shutil
        repos_root = os.path.join(workspace_path, 'repos')
        os.makedirs(repos_root, exist_ok=True)
        token = self._github_token(instance)
        wanted = {}
        for repository in instance.repositories.all():
            wanted[repository.slug] = repository
            target = os.path.join(repos_root, repository.slug)
            authed_url = repository.url.replace('https://', f'https://{token}@', 1) if token else repository.url
            try:
                if os.path.isdir(os.path.join(target, '.git')):
                    repo = git.Repo(target)
                    repo.remotes.origin.set_url(authed_url)
                    try:
                        repo.remotes.origin.fetch(repository.branch, depth=1)
                        repo.git.checkout('-B', repository.branch, f'origin/{repository.branch}')
                        repo.git.reset('--hard', f'origin/{repository.branch}')
                    finally:
                        repo.remotes.origin.set_url(repository.url)
                else:
                    shutil.rmtree(target, ignore_errors=True)
                    repo = git.Repo.clone_from(authed_url, target, branch=repository.branch, depth=1)
                    # Don't leave the token in .git/config (the AI assistant can read files here)
                    repo.remotes.origin.set_url(repository.url)
            except git.exc.GitCommandError as e:
                error = str(e).replace(token, '***') if token else str(e)
                self.deploy_notes.append(f'No se pudo sincronizar {repository.url} ({repository.branch}): {error[-300:]}')
                wanted.pop(repository.slug, None)
        # Folders of repositories that were removed from the instance
        for folder in os.listdir(repos_root):
            if folder not in wanted:
                shutil.rmtree(os.path.join(repos_root, folder), ignore_errors=True)
        return [slug for slug in wanted if os.path.isdir(os.path.join(repos_root, slug))]

    def _ensure_db_container(self, instance, network_name, notes):
        """Start the instance's Postgres with a version its Odoo supports."""
        name = f"db_{instance.name}"
        image = postgres_image(instance.odoo_version)
        existing = self._get_container(name)
        if existing is not None:
            current = existing.attrs['Config'].get('Image', '')
            if current == image:
                return existing
            if existing.status != 'running':
                existing.start()
            self._wait_for_postgres(existing)
            if self._list_user_databases(existing):
                notes.append(f"Aviso: Odoo {instance.odoo_version} recomienda {image} y la base de datos usa {current}. "
                             "No se cambia automáticamente porque ya tiene datos.")
                return existing
            # Nothing to lose yet: replace it with the right Postgres
            existing.remove(force=True, v=True)
            notes.append(f"Base de datos recreada con {image} (usaba {current})")
        self._ensure_image(image)
        return self.client.containers.run(
            image,
            name=name,
            environment={
                "POSTGRES_DB": "postgres",
                "POSTGRES_PASSWORD": "odoo",
                "POSTGRES_USER": "odoo",
            },
            network=network_name,
            detach=True
        )

    def _ensure_image(self, image):
        """
        Pull the image if it isn't local. Returns the platform to run it with: None for the
        native one, or 'linux/amd64' for images only published for amd64 (Odoo 10-15) on an
        arm64 host, which Docker then runs emulated.
        """
        try:
            self.client.images.get(image)
            return None
        except docker.errors.ImageNotFound:
            pass
        repository, tag = image.rsplit(':', 1)
        try:
            self.client.images.pull(repository, tag=tag)
            return None
        except docker.errors.APIError as e:
            # docker-py swallows the stream error ("no matching manifest for linux/arm64") and then
            # reports "no such image", so any failure here may just mean "no build for this arch"
            native_error = getattr(e, 'explanation', None) or str(e)
        print(f"{image}: native pull failed ({native_error}); trying linux/amd64 (emulated, slower)")
        try:
            self.client.images.pull(repository, tag=tag, platform='linux/amd64')
            self.client.images.get(image)
        except docker.errors.APIError as e:
            raise Exception(f"No se pudo descargar la imagen {image}: {native_error}; amd64: {getattr(e, 'explanation', None) or e}")
        return 'linux/amd64'

    def _published_port(self, container, container_port, timeout=10):
        """Host port Docker assigned to container_port, or None if it never shows up."""
        import time
        deadline = time.monotonic() + timeout
        while True:
            container.reload()
            # ports format: {'8069/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '32768'}]}
            bindings = (container.attrs['NetworkSettings'].get('Ports') or {}).get(container_port)
            if bindings:
                return int(bindings[0]['HostPort'])
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def _list_user_databases(self, db_container):
        """Odoo databases in an instance's Postgres (everything except system DBs)."""
        result = db_container.exec_run(
            "psql -U odoo -d postgres -t -A -c \"SELECT datname FROM pg_database WHERE datistemplate = false;\"",
            environment={"PGPASSWORD": "odoo"}
        )
        if result.exit_code != 0:
            raise Exception(f"No se pudo listar las bases de datos: {result.output.decode('utf-8')}")
        databases = [db.strip() for db in result.output.decode('utf-8').split('\n') if db.strip()]
        return [db for db in databases if db not in ('postgres', 'template0', 'template1')]

    def _wait_for_postgres(self, db_container, timeout=60):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if db_container.exec_run("pg_isready -U odoo").exit_code == 0:
                return
            time.sleep(1)
        raise Exception(f"Database container {db_container.name} not ready after {timeout}s")

    def deploy_instance(self, instance):
        """
        Deploys an Odoo instance with a companion Postgres container.
        """
        instance.status = Instance.Status.DEPLOYING
        instance.save()
        self.deploy_notes = []
        
        try:
            # 1. Prepare workspace
            workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            os.makedirs(workspace_path, exist_ok=True)
            
            # 2. Clone Repository if exists
            self._clone_repo(instance, workspace_path)

            # 3. Create network
            network_name = f"net_{instance.name}"
            try:
                self.client.networks.get(network_name)
            except docker.errors.NotFound:
                self.client.networks.create(network_name, driver="bridge")

            # 4. Start Postgres
            db_container_name = f"db_{instance.name}"
            self._ensure_db_container(instance, network_name, self.deploy_notes)

            # 5. Start Odoo
            odoo_container_name = f"odoo_{instance.name}"
            
            # Check if container already exists (redeploy scenario)
            existing_container = self._get_container(odoo_container_name)
            data_volume = self._resolve_data_volume(instance, existing_container)
            
            # Bind mounts are resolved by the Docker daemon, so they need host paths
            # Addons: the GitHub checkout or an empty folder (the AI assistant writes modules there)
            addons_path = os.path.join(workspace_path, 'addons')
            os.makedirs(addons_path, exist_ok=True)
            extra_repos = self._sync_extra_repos(instance, workspace_path)
            volumes = {
                data_volume: {'bind': ODOO_DATA_DIR, 'mode': 'rw'},
                host_path(self._write_odoo_config(instance, workspace_path, extra_repos)): {'bind': '/etc/odoo', 'mode': 'rw'},
                host_path(addons_path): {'bind': '/mnt/extra-addons', 'mode': 'rw'},
                host_path(os.path.join(workspace_path, 'repos')): {'bind': '/mnt/repos', 'mode': 'ro'},
                host_path(os.path.join(settings.BASE_DIR, 'orchestrator', 'odoo_addons')): {'bind': PANEL_ADDONS_DIR, 'mode': 'ro'},
            }
            
            is_redeploy = False
            try:
                odoo_container = self.client.containers.get(odoo_container_name)
                is_redeploy = True
                print(f"Container {odoo_container_name} already exists. This is a redeploy.")
                
                # Stop the container
                if odoo_container.status == 'running':
                    print("Stopping container...")
                    odoo_container.stop()
                
                # Remove the container
                print("Removing old container...")
                odoo_container.remove()
                
            except docker.errors.NotFound:
                print(f"Container {odoo_container_name} not found. This is a fresh deployment.")
            
            # Start on Traefik's network and join the private network afterwards: Docker keeps
            # published ports on the network the container started on, and older versions drop
            # them when a network connected later becomes the gateway (sorts first by name).
            try:
                self.client.networks.get("community-sh_web")
                start_network, extra_network = "community-sh_web", network_name
            except docker.errors.NotFound:
                print("Warning: community-sh_web network not found. Traefik routing may not work.")
                start_network, extra_network = network_name, None
            
            odoo_image = f"odoo:{instance.odoo_version}"
            platform = self._ensure_image(odoo_image)
            run_options = {'platform': platform} if platform else {}
            
            # Create the container
            odoo_container = self.client.containers.run(
                odoo_image,
                **run_options,
                name=odoo_container_name,
                environment={
                    "HOST": db_container_name,
                    "USER": "odoo",
                    "PASSWORD": "odoo",
                },
                network=start_network,
                volumes=volumes,
                ports={'8069/tcp': None}, # Let Docker assign a random host port
                detach=True,
                labels={
                    "traefik.enable": "true",
                    "traefik.docker.network": "community-sh_web",
                    "traefik.http.routers.odoo_" + instance.name + ".rule": f"Host(`{instance.custom_domain if instance.custom_domain else instance.name + '.localhost'}`)",
                    "traefik.http.routers.odoo_" + instance.name + ".entrypoints": "web",
                    "traefik.http.routers.odoo_" + instance.name + ".priority": "100",
                    "traefik.http.services.odoo_" + instance.name + ".loadbalancer.server.port": "8069",
                }
            )
            
            # Private network shared with the instance's database
            if extra_network:
                self.client.networks.get(extra_network).connect(odoo_container)
            
            # If this is a redeploy, update all modules
            if is_redeploy:
                print("Redeploy detected. Running module update...")
                try:
                    db_container = self.client.containers.get(db_container_name)
                    self._wait_for_postgres(db_container)
                    databases = [instance.database_name] if instance.database_name else self._list_user_databases(db_container)
                    
                    for database in databases:
                        result = odoo_container.exec_run(
                            f"odoo -u all -d {database} --stop-after-init",
                            detach=False
                        )
                        print(f"Module update for {database} (exit {result.exit_code}): {result.output.decode('utf-8')[-2000:]}")
                    
                    # Restart container to run normally
                    odoo_container.restart()
                    print("Container restarted after module update")
                except Exception as e:
                    print(f"Warning: Error during module update: {str(e)}")


            # Get the assigned port; Docker may publish it shortly after start
            host_port = self._published_port(odoo_container, '8069/tcp')
            if host_port:
                instance.port = host_port
            
            instance.container_id = odoo_container.id
            instance.data_volume = data_volume
            instance.status = Instance.Status.RUNNING
            instance.save()
            
        except Exception as e:
            instance.status = Instance.Status.ERROR
            instance.save()
            raise e
        
        return instance

    def _clone_repo(self, instance, workspace_path):
        if not instance.github_repo:
            return
        
        addons_path = os.path.join(workspace_path, 'addons')
        
        # If the directory exists, try to pull changes
        if os.path.exists(addons_path):
            try:
                print(f"Addons path already exists: {addons_path}. Pulling latest changes...")
                repo = git.Repo(addons_path)
                
                # Get the current branch name
                current_branch = repo.active_branch.name
                print(f"Current branch: {current_branch}")
                
                # Pull latest changes
                origin = repo.remotes.origin
                origin.pull(current_branch)
                print(f"Successfully pulled latest changes from {current_branch}")
                return
            except git.exc.InvalidGitRepositoryError:
                print(f"Directory exists but is not a git repository. Removing and cloning fresh...")
                import shutil
                shutil.rmtree(addons_path)
            except Exception as e:
                print(f"Error pulling changes: {str(e)}. Will try to clone fresh...")
                import shutil
                shutil.rmtree(addons_path)
        
        # Try to clone the repository with error handling
        branch = instance.github_branch or 'main'
        branches_to_try = [branch]
        
        # If the specified branch is 'main', also try 'master'
        if branch == 'main':
            branches_to_try.append('master')
        elif branch == 'master':
            branches_to_try.append('main')
        
        for branch_name in branches_to_try:
            try:
                print(f"Attempting to clone {instance.github_repo} (branch: {branch_name})")
                git.Repo.clone_from(
                    instance.github_repo, 
                    addons_path, 
                    branch=branch_name,
                    depth=1  # Shallow clone for faster performance
                )
                print(f"Successfully cloned repository on branch {branch_name}")
                return
            except git.exc.GitCommandError as e:
                print(f"Failed to clone branch '{branch_name}': {str(e)}")
                # Try next branch
                continue
            except Exception as e:
                print(f"Unexpected error cloning repository: {str(e)}")
                break
        
        # If we get here, all attempts failed
        print(f"Warning: Could not clone repository {instance.github_repo}. Continuing without custom addons.")


    def stop_instance(self, instance):
        if not instance.container_id:
            return
        try:
            container = self.client.containers.get(instance.container_id)
            container.stop()
            instance.status = Instance.Status.STOPPED
            instance.save()
        except docker.errors.NotFound:
            pass
    
    def restart_instance(self, instance):
        """Restart the Odoo container"""
        if not instance.container_id:
            return
        try:
            container = self.client.containers.get(instance.container_id)
            print(f"Restarting container {container.name}...")
            container.restart()
            instance.status = Instance.Status.RUNNING
            instance.save()
            print(f"Container {container.name} restarted successfully")
        except docker.errors.NotFound:
            print(f"Container not found for instance {instance.name}")
            
    def delete_instance(self, instance):
        """
        Stops and removes containers, networks and the instance directory.
        """
        # 1. Stop and Remove Odoo Container (by id, or by name if the id isn't known)
        if instance.container_id or self._get_container(f"odoo_{instance.name}"):
            try:
                container = self.client.containers.get(instance.container_id or f"odoo_{instance.name}")
                container.stop()
                container.remove(v=True)
            except docker.errors.NotFound:
                pass
            except Exception as e:
                print(f"Error removing Odoo container: {e}")
        
        # Named filestore volume (not removed by remove(v=True))
        data_volume = instance.data_volume or f"odoo_data_{instance.name}"
        try:
            self.client.volumes.get(data_volume).remove()
        except docker.errors.NotFound:
            pass
        except Exception as e:
            print(f"Error removing data volume {data_volume}: {e}")

        # 2. Stop and Remove DB Container
        db_container_name = f"db_{instance.name}"
        try:
            container = self.client.containers.get(db_container_name)
            container.stop()
            container.remove(v=True)
        except docker.errors.NotFound:
            pass
        except Exception as e:
            print(f"Error removing DB container: {e}")

        # 3. Remove Network (if empty/exclusive? Usually shared or unique per instance)
        # We created a unique network `net_{instance.name}`
        network_name = f"net_{instance.name}"
        try:
            network = self.client.networks.get(network_name)
            network.remove()
        except docker.errors.NotFound:
            pass
        except Exception as e:
            print(f"Error removing network: {e}")

        # 4. Delete Git branch if this instance has a custom branch
        workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
        if instance.github_repo and instance.github_branch:
            # Don't delete main/master branches
            protected_branches = ['main', 'master', 'develop', 'development']
            if instance.github_branch not in protected_branches:
                addons_path = os.path.join(workspace_path, 'addons')
                if os.path.exists(addons_path):
                    try:
                        print(f"Attempting to delete Git branch '{instance.github_branch}'...")
                        repo = git.Repo(addons_path)
                        
                        # Delete local branch
                        try:
                            repo.delete_head(instance.github_branch, force=True)
                            print(f"Deleted local branch '{instance.github_branch}'")
                        except Exception as e:
                            print(f"Warning: Could not delete local branch: {e}")
                        
                        # Delete remote branch
                        try:
                            origin = repo.remotes.origin
                            origin.push(refspec=f":{instance.github_branch}")
                            print(f"Deleted remote branch '{instance.github_branch}'")
                        except Exception as e:
                            print(f"Warning: Could not delete remote branch: {e}")
                            
                    except git.exc.InvalidGitRepositoryError:
                        print("Not a git repository, skipping branch deletion")
                    except Exception as e:
                        print(f"Warning: Error during Git branch deletion: {e}")
            else:
                print(f"Skipping deletion of protected branch: {instance.github_branch}")
        
        # 5. Remove Files
        if os.path.exists(workspace_path):
            import shutil
            shutil.rmtree(workspace_path)
            
    def copy_instance(self, instance, new_name):
        """
        Creates a complete copy of an instance including:
        - Database dump and restore
        - Filestore copy
        - Git branch creation
        """
        print(f"Starting full copy of instance {instance.name} to {new_name}")
        
        # Create the new instance record
        new_instance = Instance.objects.create(
            name=new_name,
            odoo_version=instance.odoo_version,
            github_repo=instance.github_repo,
            github_branch=new_name,  # Use new name as branch name
            database_name=instance.database_name,
            project=instance.project,
            status=Instance.Status.DEPLOYING,
            origin='duplicate'
        )
        for repository in instance.repositories.all():
            new_instance.repositories.create(url=repository.url, branch=repository.branch)
        
        try:
            # 1. Copy the database
            print("Step 1: Copying database...")
            db_source = f"db_{instance.name}"
            db_target = f"db_{new_name}"
            
            # Get source database container
            try:
                source_db_container = self.client.containers.get(db_source)
                
                # Dump the whole cluster: Odoo databases are not the 'postgres' maintenance DB
                print("Creating database dump...")
                dump_result = source_db_container.exec_run(
                    "pg_dumpall -U odoo -f /tmp/db_dump.sql",
                    environment={"PGPASSWORD": "odoo"}
                )
                
                if dump_result.exit_code != 0:
                    raise Exception(f"Database dump failed: {dump_result.output.decode('utf-8')}")
                
                # Get the dump file from the container
                dump_stream, dump_stats = source_db_container.get_archive('/tmp/db_dump.sql')
                dump_data = b''.join(dump_stream)
                print(f"Database dumped successfully ({len(dump_data)} bytes)")
                
                # Create network for new instance
                network_name = f"net_{new_name}"
                try:
                    self.client.networks.get(network_name)
                except docker.errors.NotFound:
                    self.client.networks.create(network_name, driver="bridge")
                
                # Start new PostgreSQL container
                print("Creating new database container...")
                db_image = postgres_image(instance.odoo_version)
                self._ensure_image(db_image)
                new_db_container = self.client.containers.run(
                    db_image,
                    name=db_target,
                    environment={
                        "POSTGRES_DB": "postgres",
                        "POSTGRES_PASSWORD": "odoo",
                        "POSTGRES_USER": "odoo",
                    },
                    network=network_name,
                    detach=True
                )
                
                print("Waiting for new database to be ready...")
                self._wait_for_postgres(new_db_container)
                
                # Put the dump file into the new container
                new_db_container.put_archive('/tmp', dump_data)
                
                # Restore database
                print("Restoring database...")
                restore_result = new_db_container.exec_run(
                    "psql -U odoo -d postgres -q -f /tmp/db_dump.sql",
                    environment={"PGPASSWORD": "odoo"}
                )
                
                # Note: psql reports harmless errors (e.g. role "odoo" already exists)
                print(f"Database restore completed. Exit code: {restore_result.exit_code}")
                if restore_result.output:
                    print(f"Restore output: {restore_result.output.decode('utf-8')[:500]}")
                    
            except docker.errors.NotFound:
                print(f"Source database container {db_source} not found")
                raise
            
            # 2. Copy the workspace (addons checkout)
            print("Step 2: Copying workspace...")
            source_workspace = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            target_workspace = os.path.join(settings.BASE_DIR, 'instances', new_name)
            
            if os.path.exists(source_workspace):
                import shutil
                # odoo.conf is regenerated with the new instance's master password
                shutil.copytree(source_workspace, target_workspace, ignore=shutil.ignore_patterns('odoo.conf'))
                print(f"Workspace copied from {source_workspace} to {target_workspace}")
            
            # 3. Create new Git branch if repo exists
            if instance.github_repo:
                print("Step 3: Creating Git branch...")
                source_addons = os.path.join(source_workspace, 'addons')
                target_addons = os.path.join(target_workspace, 'addons')
                
                if os.path.exists(source_addons):
                    try:
                        repo = git.Repo(target_addons)
                        
                        # Create and checkout new branch
                        new_branch = repo.create_head(new_name)
                        new_branch.checkout()
                        
                        # Push the new branch to remote
                        try:
                            origin = repo.remotes.origin
                            origin.push(new_name)
                            print(f"New branch '{new_name}' created and pushed to remote")
                        except Exception as e:
                            print(f"Warning: Could not push branch to remote: {e}")
                            
                    except Exception as e:
                        print(f"Warning: Error creating Git branch: {e}")
            
            # 4. Deploy the new instance
            print("Step 4: Deploying new instance...")
            self.deploy_instance(new_instance)
            
            # 5. Copy the filestore (attachments) between the Odoo containers
            print("Step 5: Copying filestore...")
            self._copy_filestore(f"odoo_{instance.name}", f"odoo_{new_name}")
            
            print(f"Successfully copied instance {instance.name} to {new_name}")
            return new_instance
            
        except Exception as e:
            print(f"Error during instance copy: {str(e)}")
            new_instance.status = Instance.Status.ERROR
            new_instance.save()
            raise e

    def rename_instance(self, instance, old_name):
        """
        Move an instance's Docker resources and workspace from old_name to
        instance.name. The database container (and its data) is kept; the Odoo
        container is recreated on the same filestore volume.
        """
        new_name = instance.name
        old_odoo = self._get_container(f"odoo_{old_name}")
        if old_odoo is not None:
            instance.data_volume = self._resolve_data_volume(instance, old_odoo)
            old_odoo.remove(force=True)  # keeps volumes
        elif not instance.data_volume:
            instance.data_volume = f"odoo_data_{old_name}"

        db_container = self._get_container(f"db_{old_name}")
        if db_container is not None:
            db_container.rename(f"db_{new_name}")
            try:
                new_network = self.client.networks.get(f"net_{new_name}")
            except docker.errors.NotFound:
                new_network = self.client.networks.create(f"net_{new_name}", driver="bridge")
            # Connecting after the rename registers the new DNS name
            new_network.connect(db_container)
            try:
                old_network = self.client.networks.get(f"net_{old_name}")
                old_network.disconnect(db_container)
                old_network.remove()
            except docker.errors.NotFound:
                pass

        instances_dir = os.path.join(settings.BASE_DIR, 'instances')
        old_workspace = os.path.join(instances_dir, old_name)
        new_workspace = os.path.join(instances_dir, new_name)
        if os.path.exists(old_workspace) and not os.path.exists(new_workspace):
            os.rename(old_workspace, new_workspace)

        old_traefik_config = os.path.join(settings.BASE_DIR, 'traefik', f'instance-{old_name}.yml')
        if os.path.exists(old_traefik_config):
            os.remove(old_traefik_config)

        instance.save()
        if old_odoo is not None or db_container is not None:
            self.deploy_instance(instance)

    def _copy_filestore(self, source_name, target_name):
        source = self._get_container(source_name)
        target = self._get_container(target_name)
        if source is None or target is None:
            print(f"Warning: cannot copy filestore ({source_name} -> {target_name}): container missing")
            return
        try:
            stream, _ = source.get_archive(f"{ODOO_DATA_DIR}/filestore")
            target.put_archive(ODOO_DATA_DIR, b''.join(stream))
            print(f"Filestore copied from {source_name} to {target_name}")
        except docker.errors.NotFound:
            print(f"No filestore found in {source_name}")

    def get_logs(self, instance, lines=100):
        if not instance.container_id:
            return "No container ID found."
        try:
            container = self.client.containers.get(instance.container_id)
            # logs returns bytes, need to decode
            return container.logs(tail=lines).decode('utf-8')
        except docker.errors.NotFound:
            return "Container not found."
        except Exception as e:
            return f"Error fetching logs: {str(e)}"
    
    def execute_command(self, instance, command):
        """Execute a command inside the container and return the output"""
        if not instance.container_id:
            return "No container ID found."
        
        try:
            container = self.client.containers.get(instance.container_id)
            
            # Execute command inside container without specifying workdir
            # This allows the command to run from the container's default directory
            exec_result = container.exec_run(
                command,
                stdout=True,
                stderr=True,
                stdin=False,
                tty=False,
                privileged=False,
                user=''
            )
            
            # Decode output
            output = exec_result.output.decode('utf-8')
            exit_code = exec_result.exit_code
            
            if exit_code != 0:
                return f"[Exit Code: {exit_code}]\n{output}"
            return output
            
        except docker.errors.NotFound:
            return "Container not found."
        except docker.errors.APIError as e:
            return f"Docker API Error: {str(e)}"
        except Exception as e:
            return f"Error executing command: {str(e)}"
    
    def backup_instance(self, instance, include_filestore=True, user=None):
        """
        Creates a backup of the instance (database + optionally filestore)
        Returns the Backup model instance
        """
        import zipfile
        from datetime import datetime
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{instance.name}_backup_{timestamp}.zip"
        
        # Create backups directory if it doesn't exist
        backups_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backups_dir, exist_ok=True)
        
        backup_path = os.path.join(backups_dir, backup_filename)
        
        print(f"Creating backup for instance {instance.name}...")
        
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Backup Odoo database
                print(f"Backing up database for {instance.name}...")
                db_container = self.client.containers.get(f"db_{instance.name}")
                
                # Check if database_name is specified in instance
                if instance.database_name:
                    odoo_db_name = instance.database_name
                    print(f"Using specified database name: {odoo_db_name}")
                else:
                    # List databases to find the Odoo database
                    list_dbs_result = db_container.exec_run(
                        "psql -U odoo -d postgres -t -c \"SELECT datname FROM pg_database WHERE datistemplate = false;\"",
                        environment={"PGPASSWORD": "odoo"}
                    )
                    
                    if list_dbs_result.exit_code == 0:
                        databases = [db.strip() for db in list_dbs_result.output.decode('utf-8').split('\n') if db.strip()]
                        print(f"Available databases: {databases}")
                        
                        # Filter out system databases
                        user_databases = [db for db in databases if db not in ['postgres', 'template0', 'template1']]
                        
                        if user_databases:
                            # Use the first user database (the Odoo database)
                            odoo_db_name = user_databases[0]
                            print(f"Found Odoo database: {odoo_db_name}")
                        else:
                            raise Exception(
                                f"No se encontró ninguna base de datos de usuario. "
                                f"Por favor, especifica el nombre de la base de datos en el campo 'Database Name' de la instancia. "
                                f"Bases de datos disponibles: {databases}"
                            )
                        
                        print(f"Using database: {odoo_db_name}")
                    else:
                        raise Exception(
                            "No se pudo listar las bases de datos. "
                            "Por favor, especifica el nombre de la base de datos en el campo 'Database Name' de la instancia."
                        )
                
                # Create database dump for the specific database
                dump_result = db_container.exec_run(
                    f"pg_dump -U odoo -Fc {odoo_db_name} -f /tmp/backup.dump",
                    environment={"PGPASSWORD": "odoo"}
                )
                
                if dump_result.exit_code != 0:
                    error_msg = dump_result.output.decode('utf-8')
                    raise Exception(f"Database backup failed: {error_msg}")
                
                # Get dump file
                dump_stream, _ = db_container.get_archive('/tmp/backup.dump')
                dump_data = b''.join(dump_stream)
                
                # Extract the tar archive and get the actual file
                import tarfile
                import io
                tar = tarfile.open(fileobj=io.BytesIO(dump_data))
                dump_file = tar.extractfile('backup.dump')
                zipf.writestr('database.dump', dump_file.read())
                print(f"Database '{odoo_db_name}' backed up successfully")
                
                # 2. Backup filestore if requested
                if include_filestore:
                    print("Backing up filestore from Odoo container...")
                    try:
                        odoo_container = self.client.containers.get(f"odoo_{instance.name}")
                        
                        # The filestore is typically at /var/lib/odoo/filestore/{db_name}
                        filestore_path = f"/var/lib/odoo/filestore/{odoo_db_name}"
                        print(f"Checking filestore at: {filestore_path}")
                        
                        # Check if filestore exists in container using sh -c
                        check_result = odoo_container.exec_run(
                            f"sh -c 'if [ -d {filestore_path} ]; then echo exists; else echo not_found; fi'"
                        )
                        check_output = check_result.output.decode('utf-8').strip()
                        print(f"Filestore check result: '{check_output}'")
                        
                        if 'exists' in check_output:
                            # Get filestore archive from container
                            print(f"Extracting filestore from {filestore_path}...")
                            filestore_stream, _ = odoo_container.get_archive(filestore_path)
                            filestore_data = b''.join(filestore_stream)
                            print(f"Filestore archive size: {len(filestore_data)} bytes")
                            
                            # Extract the tar and add files to backup zip
                            import tarfile
                            import io
                            tar = tarfile.open(fileobj=io.BytesIO(filestore_data))
                            file_count = 0
                            for member in tar.getmembers():
                                if member.isfile():
                                    file_data = tar.extractfile(member)
                                    # Store with 'filestore/' prefix
                                    zip_path = f'filestore/{member.name}'
                                    zipf.writestr(zip_path, file_data.read())
                                    file_count += 1
                                    if file_count <= 3:  # Log first 3 files
                                        print(f"  Added to ZIP: {zip_path}")
                            print(f"Filestore backed up successfully: {file_count} files from {filestore_path}")
                        else:
                            print(f"Warning: Filestore not found at {filestore_path}")
                    except Exception as e:
                        import traceback
                        print(f"ERROR backing up filestore: {str(e)}")
                        print(traceback.format_exc())
                else:
                    print("Skipping filestore backup (not requested)")
                
                # 3. Add metadata
                metadata = {
                    'instance_name': instance.name,
                    'odoo_version': instance.odoo_version,
                    'backup_date': timestamp,
                    'include_filestore': include_filestore,
                    'database_name': odoo_db_name,
                    'github_repo': instance.github_repo or '',
                    'github_branch': instance.github_branch or ''
                }
                import json
                zipf.writestr('metadata.json', json.dumps(metadata, indent=2))
                
            print(f"Backup created successfully: {backup_path}")
            
            # Create backup record in database
            from ..backup_models import Backup
            file_size = os.path.getsize(backup_path)
            print(f"Backup file size: {file_size} bytes ({file_size / (1024 * 1024):.2f} MB)")
            
            backup_record = Backup.objects.create(
                instance=instance,
                filename=backup_filename,
                file_path=backup_path,
                include_filestore=include_filestore,
                file_size=file_size,
                created_by=user
            )
            print(f"Backup record created: ID={backup_record.pk}, Size={backup_record.file_size} bytes")
            
            return backup_record
            
        except Exception as e:
            print(f"Error creating backup: {str(e)}")
            if os.path.exists(backup_path):
                os.remove(backup_path)
            raise e
    
    def restore_instance(self, instance, backup_file_path):
        """
        Restores an instance from a backup file
        """
        import zipfile
        import tempfile
        import json
        
        print(f"Restoring instance {instance.name} from backup...")
        backup_format = read_backup_metadata(backup_file_path)['format']
        if backup_format == 'pg_dump':
            # A bare custom-format dump: wrap it like a panel backup without filestore
            wrapped = tempfile.NamedTemporaryFile(suffix='.zip', delete=False).name
            with zipfile.ZipFile(wrapped, 'w') as zf:
                zf.write(backup_file_path, 'database.dump')
                zf.writestr('metadata.json', '{}')
            backup_file_path, backup_format = wrapped, 'panel'
        native = backup_format == 'odoo'
        
        try:
            with zipfile.ZipFile(backup_file_path, 'r') as zipf:
                # List all files in the ZIP for debugging
                zip_contents = zipf.namelist()
                print(f"ZIP file contains {len(zip_contents)} entries")
                filestore_entries = [f for f in zip_contents if f.startswith('filestore/')]
                print(f"Filestore entries found: {len(filestore_entries)}")
                if filestore_entries:
                    print(f"First few filestore entries: {filestore_entries[:5]}")
                
                # Extract to temp directory
                temp_dir = tempfile.mkdtemp()
                zipf.extractall(temp_dir)
                
                # Read metadata (Odoo's own backups carry manifest.json instead)
                metadata_path = os.path.join(temp_dir, 'metadata.json')
                if os.path.exists(metadata_path):
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                else:
                    metadata = {'database_name': read_backup_metadata(backup_file_path)['database_name']}
                    metadata = {k: v for k, v in metadata.items() if v}
                
                print(f"Backup metadata: {metadata}")
                
                # 1. Restore database
                print("Restoring database...")
                db_container = self.client.containers.get(f"db_{instance.name}")
                
                # Read dump file: custom format (panel) or plain SQL (Odoo database manager)
                dump_path = os.path.join(temp_dir, 'dump.sql' if native else 'database.dump')
                with open(dump_path, 'rb') as f:
                    dump_data = f.read()
                
                # Create tar archive for docker
                import tarfile
                import io
                tar_stream = io.BytesIO()
                tar = tarfile.open(fileobj=tar_stream, mode='w')
                tarinfo = tarfile.TarInfo(name='restore.sql' if native else 'restore.dump')
                tarinfo.size = len(dump_data)
                tar.addfile(tarinfo, io.BytesIO(dump_data))
                tar.close()
                tar_stream.seek(0)
                
                # Put file in container
                db_container.put_archive('/tmp', tar_stream.read())
                
                # Get database name - prioritize instance's database_name if set
                if instance.database_name:
                    odoo_db_name = instance.database_name
                    print(f"Using instance database name: {odoo_db_name}")
                else:
                    odoo_db_name = metadata.get('database_name', instance.name.replace('-', '_'))
                    print(f"Using metadata/default database name: {odoo_db_name}")
                
                # The name comes from an uploaded file and ends up in psql/pg_restore commands
                from ..permissions import validate_database_name
                validate_database_name(odoo_db_name)
                
                # Odoo keeps connections open: stop it and close them, or DROP DATABASE fails
                odoo_container = self._get_container(f"odoo_{instance.name}")
                if odoo_container is not None and odoo_container.status == 'running':
                    odoo_container.stop()
                db_container.exec_run(
                    ['psql', '-U', 'odoo', '-d', 'postgres', '-c',
                     f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{odoo_db_name}' AND pid <> pg_backend_pid()"],
                    environment={"PGPASSWORD": "odoo"}
                )
                
                # Drop and recreate the database
                print(f"Dropping and recreating database '{odoo_db_name}'...")
                drop_result = db_container.exec_run(
                    ['psql', '-U', 'odoo', '-d', 'postgres', '-c', f'DROP DATABASE IF EXISTS "{odoo_db_name}"'],
                    environment={"PGPASSWORD": "odoo"}
                )
                if drop_result.exit_code != 0:
                    raise Exception(f"No se pudo borrar la base de datos {odoo_db_name}: {drop_result.output.decode()}")
                
                create_result = db_container.exec_run(
                    ['psql', '-U', 'odoo', '-d', 'postgres', '-c', f'CREATE DATABASE "{odoo_db_name}"'],
                    environment={"PGPASSWORD": "odoo"}
                )
                if create_result.exit_code != 0:
                    raise Exception(f"No se pudo crear la base de datos {odoo_db_name}: {create_result.output.decode()}")
                
                # Restore dump to the database (without -c flag to avoid clean errors)
                if native:
                    restore_result = db_container.exec_run(
                        ['psql', '-U', 'odoo', '-d', odoo_db_name, '-q', '-f', '/tmp/restore.sql'],
                        environment={"PGPASSWORD": "odoo"}
                    )
                else:
                    restore_result = db_container.exec_run(
                        f"pg_restore -U odoo -d {odoo_db_name} --no-owner --no-acl /tmp/restore.dump",
                        environment={"PGPASSWORD": "odoo"}
                    )
                print(f"Database restore completed. Exit code: {restore_result.exit_code}")
                if restore_result.output:
                    print(f"Restore output: {restore_result.output.decode()}")
                
                # Filestore steps exec into the Odoo container, so it must be running again
                if odoo_container is not None:
                    odoo_container.start()
                
                # 2. Restore filestore if exists
                filestore_dir = os.path.join(temp_dir, 'filestore')
                print(f"Checking for filestore at: {filestore_dir}")
                print(f"Filestore exists: {os.path.exists(filestore_dir)}")
                
                if os.path.exists(filestore_dir):
                    print("Restoring filestore to Odoo container...")
                    try:
                        odoo_container = self.client.containers.get(f"odoo_{instance.name}")
                        
                        # Check what's inside the filestore directory
                        filestore_contents = os.listdir(filestore_dir)
                        print(f"Filestore directory contents: {filestore_contents}")
                        
                        if not filestore_contents:
                            print("Warning: Filestore directory is empty")
                            raise Exception("Filestore directory is empty")
                        
                        # The filestore backup includes the original DB name as a subdirectory
                        # We need to get the actual files from inside that subdirectory
                        actual_filestore_dir = filestore_dir
                        
                        # Panel backups nest the files under the original database name; Odoo's own
                        # backups put them directly in filestore/
                        if not native and len(filestore_contents) == 1 and os.path.isdir(os.path.join(filestore_dir, filestore_contents[0])):
                            actual_filestore_dir = os.path.join(filestore_dir, filestore_contents[0])
                            print(f"Using subdirectory as filestore source: {actual_filestore_dir}")
                        
                        # Count files to restore
                        file_count = 0
                        for root, dirs, files in os.walk(actual_filestore_dir):
                            file_count += len(files)
                        
                        print(f"Total files to restore: {file_count}")
                        
                        if file_count == 0:
                            print("Warning: No files found in filestore directory")
                            raise Exception("No files found in filestore")
                        
                        # Create tar archive with filestore contents
                        tar_stream = io.BytesIO()
                        tar = tarfile.open(fileobj=tar_stream, mode='w')
                        
                        # Add all files from actual filestore directory
                        files_added = 0
                        for root, dirs, files in os.walk(actual_filestore_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # Get relative path from actual_filestore_dir
                                arcname = os.path.relpath(file_path, actual_filestore_dir)
                                tar.add(file_path, arcname=arcname)
                                files_added += 1
                        
                        print(f"Added {files_added} files to tar archive")
                        tar.close()
                        
                        tar_size = tar_stream.tell()
                        print(f"Tar archive size: {tar_size} bytes")
                        tar_stream.seek(0)
                        
                        # Create filestore directory in container
                        filestore_path = f"/var/lib/odoo/filestore/{odoo_db_name}"
                        print(f"Creating filestore directory in container: {filestore_path}")
                        odoo_container.exec_run(f"mkdir -p {filestore_path}", user='root')
                        
                        # Put filestore archive in container to the correct database folder
                        print(f"Uploading filestore to container...")
                        odoo_container.put_archive(filestore_path, tar_stream.read())
                        
                        # Verify files were copied
                        verify_result = odoo_container.exec_run(f"ls -la {filestore_path}")
                        print(f"Files in container after restore: {verify_result.output.decode('utf-8')}")
                        
                        # Set correct ownership
                        print(f"Setting ownership...")
                        odoo_container.exec_run(f"chown -R odoo:odoo {filestore_path}", user='root')
                        
                        print(f"Filestore restored successfully to container at {filestore_path}")
                    except Exception as e:
                        import traceback
                        print(f"ERROR: Could not restore filestore: {str(e)}")
                        print(traceback.format_exc())
                else:
                    print("Warning: No filestore directory found in backup")
                
                # Restart instance
                print("Restarting instance...")
                self.restart_instance(instance)
                
                # Cleanup
                import shutil
                shutil.rmtree(temp_dir)
                
                print("Restore completed successfully")
                
        except Exception as e:
            print(f"Error restoring backup: {str(e)}")
            raise e
