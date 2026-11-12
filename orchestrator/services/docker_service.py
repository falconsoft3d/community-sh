"""Docker orchestration of the Odoo instances: deploy, start/stop, delete. Databases, copies, backups and
day-to-day operations live in their own modules (docker_databases, docker_copies, docker_backups,
docker_operations) as mixins of DockerService."""
import docker
import os
import git
from django.conf import settings
from ..models import Instance
from ..task_log import progress
from ..instance_env import instance_environment
from .docker_helpers import (  # noqa: F401
    BROWSER_SCRIPT,
    DEMO_MIN_VERSION,
    ODOO_DATA_DIR,
    PANEL_ADDONS_DIR,
    PANEL_INTERNAL_URL,
    PIP_INSTALL,
    RESTART_POLICY,
    admin_login_secret,
    host_path,
    log_config,
    memory_options,
    odoo_command,
    odoo_config_target,
    odoo_major,
    odoo_password_hash,
    pip_user_command,
    postgres_image,
    published_ip,
    read_backup_metadata,
)
from .docker_databases import DatabaseMixin
from .docker_copies import CopyMixin
from .docker_operations import OperationsMixin
from .docker_backups import BackupMixin


class DockerService(DatabaseMixin, CopyMixin, OperationsMixin, BackupMixin):
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
        # Odoo 8-10 also load web_kanban server-wide by default
        server_wide = 'base,web,web_kanban' if odoo_major(instance.odoo_version) <= 10 else 'base,web'
        # community_sh_ai: "/ia ..." in a chatter asks the panel's AI assistant (controllers load server-wide,
        # the chatter hook once the module is installed in the database)
        # Demos: /?name opens the database name; without it, the default one, and the list of databases stays hidden
        demo = bool(instance.demo_default_db) and odoo_major(instance.odoo_version) >= DEMO_MIN_VERSION
        demo_lines = f"community_sh_demo_default = {instance.demo_default_db}\nlist_db = False\n" if demo else ''
        panel_login = (f"server_wide_modules = {server_wide},community_sh_login,community_sh_ai"
                       f"{',community_sh_demo' if demo else ''}\n{demo_lines}"
                       f"community_sh_secret = {admin_login_secret(instance)}\n"
                       f"community_sh_panel_url = {PANEL_INTERNAL_URL}\n"
                       f"community_sh_instance = {instance.name}\n")
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
        for name in ('odoo.conf', 'openerp-server.conf'):
            stale = os.path.join(config_dir, name)
            if name != os.path.basename(config_path) and os.path.exists(stale):
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
            from .github import authed_url as with_token
            authed_url = with_token(repository.url, token)
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
            if existing.attrs.get('HostConfig', {}).get('RestartPolicy', {}).get('Name') != RESTART_POLICY['Name']:
                # Databases created before the restart policy: they come back after a reboot too
                existing.update(restart_policy=RESTART_POLICY)
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
            detach=True,
            restart_policy=RESTART_POLICY,
            log_config=log_config(),
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

    PORT_RANGE = (20000, 40000)

    def _run_on_fixed_port(self, name, preferred, run):
        """
        Start a container publishing 8069 on an explicit host port: a port Docker picks itself
        changes on every restart (of the container or the server) and breaks the stored links.
        Keeps the instance's port when it's still free. Returns (container, port).
        """
        import random
        from ..container_models import Container
        from ..models import Instance
        used = set(Instance.objects.exclude(port=None).values_list('port', flat=True))
        used |= set(Container.objects.exclude(port=None).values_list('port', flat=True))
        candidates = [preferred] if preferred else []
        candidates += random.sample([p for p in range(*self.PORT_RANGE) if p not in used], 15)
        for port in candidates:
            try:
                return run(port), port
            except docker.errors.APIError as e:
                message = str(e).lower()
                if not any(text in message for text in ('allocated', 'address already in use', 'ports are not available')):
                    raise
                print(f"Port {port} is busy, trying another one")
                stale = self._get_container(name)
                if stale is not None:
                    stale.remove(force=True)
        raise Exception('No se encontró un puerto libre para publicar Odoo')

    AI_MODULE = 'community_sh_ai'

    def module_known(self, db_container, database, module):
        output = db_container.exec_run(['psql', '-U', 'odoo', '-d', database, '-Atc',
                                        f"SELECT count(*) FROM ir_module_module WHERE name = '{module}'"],
                                       environment={"PGPASSWORD": "odoo"}).output.decode().strip()
        return output == '1'

    def refresh_module_list(self, instance, odoo_container, database):
        """Rescan the addons folders (Apps → Update Apps List) through odoo shell (Odoo 9+)."""
        script = "env['ir.module.module'].update_list()\nenv.cr.commit()\n"
        return odoo_container.exec_run(
            ['sh', '-c', f'printf "%s" "$SCRIPT" | {odoo_command(instance.odoo_version)} shell -d {database}'],
            environment={'SCRIPT': script})

    def _install_ai_module(self, instance, odoo_container, db_container_name):
        """
        "/ia ..." in Odoo chatters: community_sh_ai installs itself (auto_install) in new databases
        with mail; add it to existing ones. Only when the AI assistant is configured. Odoo 8 has no
        shell (and its old mail API isn't hooked), so it's skipped there.
        """
        from .ai import get_ai_config
        if odoo_major(instance.odoo_version) < 9 or get_ai_config() is None or instance.origin == 'trial':
            return
        db_container = self._get_container(db_container_name)
        if db_container is None:
            return
        try:
            self._wait_for_postgres(db_container)
            for database in self._list_user_databases(db_container):
                states = db_container.exec_run(
                    ['psql', '-U', 'odoo', '-d', database, '-Atc',
                     f"SELECT name, state FROM ir_module_module WHERE name IN ('mail', '{self.AI_MODULE}')"],
                    environment={"PGPASSWORD": "odoo"}).output.decode()
                states = dict(line.split('|', 1) for line in states.splitlines() if '|' in line)
                if states.get('mail') != 'installed' or states.get(self.AI_MODULE) == 'installed':
                    continue
                script = (f"env['ir.module.module'].update_list()\n"
                          f"env['ir.module.module'].search([('name', '=', '{self.AI_MODULE}')]).button_immediate_install()\n"
                          "env.cr.commit()\n")
                result = odoo_container.exec_run(
                    ['sh', '-c', f'printf "%s" "$SCRIPT" | {odoo_command(instance.odoo_version)} shell -d {database}'],
                    environment={'SCRIPT': script})
                if result.exit_code == 0:
                    self.deploy_notes.append(f'Asistente de IA en Odoo activado en {database}: escribe «/ia …» en cualquier chatter')
                else:
                    print(f"{self.AI_MODULE} install in {database} failed: {result.output.decode(errors='replace')[-800:]}")
        except Exception as e:
            print(f"Warning: could not install {self.AI_MODULE}: {e}")

    def apply_memory_limits(self, instances=None):
        """
        Apply the memory cap of each instance to its running Odoo container, live (docker update, no restart).
        "No limit" (0) is applied on the next deploy. Returns the names of the instances whose cap changed.
        """
        from ..models import Instance
        queryset = Instance.objects.filter(memory_limit_mb__gt=0)
        if instances is not None:
            queryset = queryset.filter(pk__in=[i.pk for i in instances])
        wanted = {instance.name: instance.memory_limit_mb * 1024 * 1024 for instance in queryset}
        changed = []
        for container in self.client.containers.list(filters={'name': 'odoo_'}):
            name = container.name[len('odoo_'):]
            if name not in wanted or container.attrs.get('HostConfig', {}).get('Memory') == wanted[name]:
                continue
            # Lowering the cap below what it uses now would make the kernel kill Odoo: wait (retried every minute)
            usage = (container.stats(stream=False).get('memory_stats') or {}).get('usage') or 0
            if usage > wanted[name] * 0.9:
                print(f'Límite de memoria de {name} pendiente: usa {usage // 1048576} MB, cerca del tope '
                      f'{wanted[name] // 1048576} MB (súbelo o se aplicará cuando baje)')
                continue
            try:
                container.update(mem_limit=wanted[name], memswap_limit=wanted[name])
                changed.append(name)
            except docker.errors.APIError as e:
                # Below what it uses right now, for example: it stays as it was and is retried
                print(f'Límite de memoria de {name}: {getattr(e, "explanation", None) or e}')
        return changed

    def sync_published_ports(self):
        """
        Store the host port each running Odoo container actually publishes. Containers
        deployed before fixed ports got a new random one on every restart. Returns the
        names of the instances that changed.
        """
        from ..models import Instance
        published = {}
        for container in self.client.containers.list(filters={'name': 'odoo_'}):
            bindings = (container.attrs['NetworkSettings'].get('Ports') or {}).get('8069/tcp')
            if bindings:
                published[container.name[len('odoo_'):]] = int(bindings[0]['HostPort'])
        changed = []
        for instance in Instance.objects.filter(name__in=published):
            if instance.port != published[instance.name]:
                Instance.objects.filter(pk=instance.pk).update(port=published[instance.name])
                changed.append(instance.name)
        return changed

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
        from ..permissions import DATABASE_NAME_RE
        skipped = [db for db in databases if not DATABASE_NAME_RE.match(db)]
        if skipped:
            print(f"Skipping databases with unsupported names: {skipped!r}")
        return [db for db in databases if db not in ('postgres', 'template0', 'template1') and DATABASE_NAME_RE.match(db)]

    def _wait_for_postgres(self, db_container, timeout=180):
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Over TCP: on first start the image runs a socket-only server to initialise the
            # cluster, then restarts it; that one must not count as ready
            if db_container.exec_run("pg_isready -U odoo -h 127.0.0.1").exit_code == 0:
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
            progress(5, 'Preparando el espacio de trabajo')
            workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            os.makedirs(workspace_path, exist_ok=True)
            
            # 2. Clone Repository if exists
            progress(10, 'Sincronizando el repositorio de GitHub')
            self._clone_repo(instance, workspace_path)

            # 3. Create network
            network_name = f"net_{instance.name}"
            try:
                self.client.networks.get(network_name)
            except docker.errors.NotFound:
                self.client.networks.create(network_name, driver="bridge")

            # 4. Start Postgres
            progress(25, 'Base de datos PostgreSQL')
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
            progress(35, 'Repositorios de módulos')
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
            progress(50, f'Imagen {odoo_image}')
            platform = self._ensure_image(odoo_image)
            run_options = {'platform': platform} if platform else {}
            
            # Create the container
            progress(60, 'Arrancando el contenedor de Odoo')
            odoo_container, host_port = self._run_on_fixed_port(odoo_container_name, instance.port, lambda port: self.client.containers.run(
                odoo_image,
                **run_options,
                name=odoo_container_name,
                environment={
                    # The instance's own variables first: the database connection always wins
                    **instance_environment(instance),
                    "HOST": db_container_name,
                    "USER": "odoo",
                    "PASSWORD": "odoo",
                },
                network=start_network,
                volumes=volumes,
                ports={'8069/tcp': (published_ip(), port)},
                detach=True,
                restart_policy=RESTART_POLICY,
                log_config=log_config(),
                **memory_options(instance),
                labels={
                    "traefik.enable": "true",
                    "traefik.docker.network": "community-sh_web",
                    "traefik.http.routers.odoo_" + instance.name + ".rule": f"Host(`{instance.custom_domain if instance.custom_domain else instance.name + '.localhost'}`)",
                    "traefik.http.routers.odoo_" + instance.name + ".entrypoints": "web",
                    "traefik.http.routers.odoo_" + instance.name + ".priority": "100",
                    "traefik.http.services.odoo_" + instance.name + ".loadbalancer.server.port": "8069",
                }
            ))
            
            # Private network shared with the instance's database
            if extra_network:
                self.client.networks.get(extra_network).connect(odoo_container)
            
            # If this is a redeploy, update all modules
            if is_redeploy:
                progress(70, 'Actualizando los módulos')
                print("Redeploy detected. Running module update...")
                try:
                    db_container = self.client.containers.get(db_container_name)
                    self._wait_for_postgres(db_container)
                    databases = [instance.database_name] if instance.database_name else self._list_user_databases(db_container)
                    
                    for database in databases:
                        result = odoo_container.exec_run(
                            f"{odoo_command(instance.odoo_version)} -u all -d {database} --stop-after-init",
                            detach=False
                        )
                        print(f"Module update for {database} (exit {result.exit_code}): {result.output.decode('utf-8')[-2000:]}")
                    
                    # Restart container to run normally
                    odoo_container.restart()
                    print("Container restarted after module update")
                except Exception as e:
                    print(f"Warning: Error during module update: {str(e)}")

            self._install_ai_module(instance, odoo_container, db_container_name)

            if instance.browser:
                # The container is new on every deploy: Chrome is installed again
                progress(85, 'Instalando Google Chrome (WhatsApp Web)')
                try:
                    self.deploy_notes.append(self.install_browser(instance, odoo_container))
                except Exception as e:
                    self.deploy_notes.append(f'No se pudo instalar Google Chrome: {e}')

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
        """The main repository of the instance in <workspace>/addons, with the token of its owner (it may be
        private). A failed update keeps the code there; without any code the deploy fails instead of going on empty."""
        if not instance.github_repo:
            return
        import shutil
        from .github import authed_url as with_token
        token = self._github_token(instance)
        authed_url = with_token(instance.github_repo, token)
        clean = lambda error: str(error).replace(token, '***')[-300:] if token else str(error)[-300:]  # noqa: E731
        addons_path = os.path.join(workspace_path, 'addons')
        has_code = os.path.isdir(os.path.join(addons_path, '.git'))
        error = ''
        if has_code:
            try:
                repo = git.Repo(addons_path)
                branch = repo.active_branch.name
                repo.remotes.origin.set_url(authed_url)
                try:
                    repo.remotes.origin.pull(branch)
                finally:
                    # Don't leave the token in .git/config (the AI assistant can read files here)
                    repo.remotes.origin.set_url(instance.github_repo)
                print(f"Successfully pulled latest changes from {branch}")
                return
            except Exception as e:
                error = clean(e)
                print(f"Error pulling changes: {error}. Will try to clone fresh...")

        branch = instance.github_branch or 'main'
        branches_to_try = [branch] + ({'main': ['master'], 'master': ['main']}.get(branch) or [])
        # Into another folder: the code in place is only replaced by a clone that worked
        fresh_path = f'{addons_path}.new'
        for branch_name in branches_to_try:
            shutil.rmtree(fresh_path, ignore_errors=True)
            try:
                print(f"Attempting to clone {instance.github_repo} (branch: {branch_name})")
                repo = git.Repo.clone_from(authed_url, fresh_path, branch=branch_name, depth=1)
                repo.remotes.origin.set_url(instance.github_repo)
                shutil.rmtree(addons_path, ignore_errors=True)
                os.rename(fresh_path, addons_path)
                print(f"Successfully cloned repository on branch {branch_name}")
                return
            except git.exc.GitCommandError as e:
                error = clean(e)
                print(f"Failed to clone branch '{branch_name}': {error}")
        shutil.rmtree(fresh_path, ignore_errors=True)
        message = f'No se pudo obtener {instance.github_repo} ({branch}): {error}'
        if has_code:
            self.deploy_notes.append(f'{message}. Sigue el código anterior.')
            return
        raise Exception(message)


    def stop_instance(self, instance):
        if not instance.container_id:
            return
        try:
            container = self.client.containers.get(instance.container_id)
            container.stop()
            instance.status = Instance.Status.STOPPED
            instance.save()
            self._refresh_routes(instance)
        except docker.errors.NotFound:
            pass

    @staticmethod
    def _refresh_routes(instance):
        """The Traefik routes follow the state of the instance (a stopped one has none)."""
        from ..traefik_service import TraefikService
        TraefikService.generate_instance_config(instance)
    
    def _start_db_container(self, instance):
        """The instance's Postgres, started if it was stopped (a reboot without restart policy), and kept up from now on."""
        db_container = self._get_container(f'db_{instance.name}')
        if db_container is None:
            return None
        if db_container.attrs.get('HostConfig', {}).get('RestartPolicy', {}).get('Name') != RESTART_POLICY['Name']:
            db_container.update(restart_policy=RESTART_POLICY)
        if db_container.status != 'running':
            print(f"Starting database container {db_container.name}...")
            db_container.start()
            self._wait_for_postgres(db_container)
        return db_container

    def restart_instance(self, instance):
        """Restart the Odoo container, starting its database first if it was stopped"""
        if not instance.container_id:
            return
        try:
            self._start_db_container(instance)
            container = self.client.containers.get(instance.container_id)
            if container.attrs.get('HostConfig', {}).get('RestartPolicy', {}).get('Name') != RESTART_POLICY['Name']:
                container.update(restart_policy=RESTART_POLICY)
            print(f"Restarting container {container.name}...")
            container.restart()
            instance.status = Instance.Status.RUNNING
            instance.save()
            self._refresh_routes(instance)
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
