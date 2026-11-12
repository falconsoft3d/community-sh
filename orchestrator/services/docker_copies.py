"""Copies of an instance (duplicate, demos) and renaming one. Part of DockerService."""
import docker
import os
import git
from django.conf import settings
from ..models import Instance
from ..task_log import progress
from .docker_helpers import (
    ODOO_DATA_DIR,
    RESTART_POLICY,
    postgres_image,
)


class CopyMixin:
            
    def copy_instance(self, instance, new_name, project=None, create_branch=True, origin='duplicate', neutralize=None):
        """
        neutralize: 'full' (a staging copy: no mail, no scheduled actions, no payments) or 'mail' (a demo: the
        same but its scheduled actions keep running), applied to the copied databases before its Odoo starts.
        Creates a complete copy of an instance including:
        - Database dump and restore
        - Filestore copy
        - Git branch creation (create_branch=False keeps the branch of the source: demos)
        project: where the copy goes (default: the project of the source).
        """
        print(f"Starting full copy of instance {instance.name} to {new_name}")
        
        # Create the new instance record
        new_instance = Instance.objects.create(
            name=new_name,
            odoo_version=instance.odoo_version,
            github_repo=instance.github_repo,
            github_branch=new_name if create_branch else instance.github_branch,
            database_name=instance.database_name,
            demo_default_db=instance.demo_default_db,
            # Same databases, same administrator (a demo gets a new password right after)
            admin_login=instance.admin_login,
            admin_password=instance.admin_password,
            admin_database=instance.admin_database,
            # A copy runs the same code with the same configuration; a demo for a prospect doesn't get it
            env_vars='' if origin == 'trial' else instance.env_vars,
            project=project or instance.project,
            status=Instance.Status.DEPLOYING,
            origin=origin,
        )
        for repository in instance.repositories.all():
            new_instance.repositories.create(url=repository.url, branch=repository.branch)
        
        try:
            # 1. Copy the database
            progress(5, 'Copiando la base de datos')
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
                    detach=True,
                    restart_policy=RESTART_POLICY,
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
                if restore_result.exit_code == 2:  # could not connect: nothing was restored
                    raise Exception(f"No se pudo restaurar la base de datos: {restore_result.output.decode('utf-8', errors='replace')[-300:]}")
                if restore_result.output:
                    print(f"Restore output: {restore_result.output.decode('utf-8')[:500]}")
                # Before its Odoo starts: a copy of production must not mail customers or charge cards
                if neutralize:
                    progress(35, 'Neutralizando la copia (correo, tareas programadas, pagos)')
                    for note in self.neutralize_databases(new_instance, crons=neutralize == 'full'):
                        print(note)

            except docker.errors.NotFound:
                print(f"Source database container {db_source} not found")
                raise
            
            # 2. Copy the workspace (addons checkout)
            progress(40, 'Copiando el espacio de trabajo')
            print("Step 2: Copying workspace...")
            source_workspace = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            target_workspace = os.path.join(settings.BASE_DIR, 'instances', new_name)
            
            if os.path.exists(source_workspace):
                import shutil
                # odoo.conf is regenerated with the new instance's master password
                shutil.copytree(source_workspace, target_workspace, ignore=shutil.ignore_patterns('odoo.conf'))
                print(f"Workspace copied from {source_workspace} to {target_workspace}")
            
            # 3. Create new Git branch if repo exists
            if instance.github_repo and create_branch:
                progress(45, 'Creando la rama de Git')
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
            progress(50, 'Desplegando la nueva instancia')
            print("Step 4: Deploying new instance...")
            self.deploy_instance(new_instance)
            
            # 5. Copy the filestore (attachments) between the Odoo containers
            progress(85, 'Copiando los adjuntos (filestore)')
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
