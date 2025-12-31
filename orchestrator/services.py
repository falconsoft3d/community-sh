import docker
import os
import git
from django.conf import settings
from .models import Instance

class DockerService:
    def __init__(self):
        self.client = docker.from_env()

    def deploy_instance(self, instance):
        """
        Deploys an Odoo instance with a companion Postgres container.
        """
        instance.status = Instance.Status.DEPLOYING
        instance.save()
        
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
            try:
                self.client.containers.get(db_container_name)
            except docker.errors.NotFound:
                self.client.containers.run(
                    "postgres:13",
                    name=db_container_name,
                    environment={
                        "POSTGRES_DB": "postgres",
                        "POSTGRES_PASSWORD": "odoo",
                        "POSTGRES_USER": "odoo",
                    },
                    network=network_name,
                    detach=True
                )

            # 5. Start Odoo
            odoo_container_name = f"odoo_{instance.name}"
            
            # Prepare data persistence directory
            data_path = os.path.join(workspace_path, 'data')
            os.makedirs(data_path, exist_ok=True)
            
            volumes = {}
            # Mount data directory for Odoo filestore and sessions
            volumes[data_path] = {'bind': '/var/lib/odoo', 'mode': 'rw'}
            
            # If we cloned addons, mount them
            addons_path = os.path.join(workspace_path, 'addons')
            if os.path.exists(addons_path):
                # We mount it to /mnt/extra-addons which is standard in Odoo images
                volumes[addons_path] = {'bind': '/mnt/extra-addons', 'mode': 'rw'}
            
            
            # Check if container already exists (redeploy scenario)
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
            
            # Create the container
            odoo_container = self.client.containers.run(
                f"odoo:{instance.odoo_version}",
                name=odoo_container_name,
                environment={
                    "HOST": db_container_name,
                    "USER": "odoo",
                    "PASSWORD": "odoo",
                },
                network=network_name,
                volumes=volumes,
                ports={'8069/tcp': None}, # Let Docker assign a random host port
                detach=True,
                labels={
                    "traefik.enable": "true",
                    "traefik.docker.network": "web",
                    "traefik.http.routers.odoo_" + instance.name + ".rule": f"Host(`{instance.name}.localhost`)",
                    "traefik.http.routers.odoo_" + instance.name + ".entrypoints": "web",
                    "traefik.http.services.odoo_" + instance.name + ".loadbalancer.server.port": "8069",
                }
            )
            
            # If this is a redeploy, update all modules
            if is_redeploy:
                print("Redeploy detected. Running module update...")
                try:
                    # Wait a bit for Odoo to start
                    import time
                    time.sleep(5)
                    
                    # Run update all command
                    result = odoo_container.exec_run(
                        "odoo -u all -d postgres --stop-after-init",
                        detach=False
                    )
                    print(f"Module update output: {result.output.decode('utf-8')}")
                    
                    # Restart container to run normally
                    odoo_container.restart()
                    print("Container restarted after module update")
                except Exception as e:
                    print(f"Warning: Error during module update: {str(e)}")


            # Connect Odoo container to the proxy network (web)
            try:
                proxy_network = self.client.networks.get("web")
                proxy_network.connect(odoo_container)
            except Exception as e:
                print(f"Warning: Could not connect to proxy network: {e}")

            # Get the assigned port
            odoo_container.reload()
            # ports format: {'8069/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '32768'}]}
            ports = odoo_container.attrs['NetworkSettings']['Ports']
            if '8069/tcp' in ports and ports['8069/tcp']:
                host_port = ports['8069/tcp'][0]['HostPort']
                instance.port = int(host_port)
            
            instance.container_id = odoo_container.id
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
            pass
            
    def delete_instance(self, instance):
        """
        Stops and removes containers, networks and the instance directory.
        """
        # 1. Stop and Remove Odoo Container
        if instance.container_id:
            try:
                container = self.client.containers.get(instance.container_id)
                container.stop()
                container.remove()
            except docker.errors.NotFound:
                pass
            except Exception as e:
                print(f"Error removing Odoo container: {e}")

        # 2. Stop and Remove DB Container
        db_container_name = f"db_{instance.name}"
        try:
            container = self.client.containers.get(db_container_name)
            container.stop()
            container.remove()
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
            status=Instance.Status.DEPLOYING,
            origin='duplicate'
        )
        
        try:
            # 1. Copy the database
            print("Step 1: Copying database...")
            db_source = f"db_{instance.name}"
            db_target = f"db_{new_name}"
            
            # Get source database container
            try:
                source_db_container = self.client.containers.get(db_source)
                
                # Create dump file inside the container
                print("Creating database dump...")
                dump_result = source_db_container.exec_run(
                    "pg_dump -U odoo -Fc postgres -f /tmp/db_dump.sql",
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
                new_db_container = self.client.containers.run(
                    "postgres:13",
                    name=db_target,
                    environment={
                        "POSTGRES_DB": "postgres",
                        "POSTGRES_PASSWORD": "odoo",
                        "POSTGRES_USER": "odoo",
                    },
                    network=network_name,
                    detach=True
                )
                
                # Wait for database to be ready
                import time
                print("Waiting for new database to be ready...")
                time.sleep(5)
                
                # Put the dump file into the new container
                new_db_container.put_archive('/tmp', dump_data)
                
                # Restore database
                print("Restoring database...")
                restore_result = new_db_container.exec_run(
                    "pg_restore -U odoo -d postgres -c /tmp/db_dump.sql",
                    environment={"PGPASSWORD": "odoo"}
                )
                
                # Note: pg_restore may have warnings but still work
                print(f"Database restore completed. Exit code: {restore_result.exit_code}")
                if restore_result.output:
                    print(f"Restore output: {restore_result.output.decode('utf-8')[:500]}")
                    
            except docker.errors.NotFound:
                print(f"Source database container {db_source} not found")
                raise
            
            # 2. Copy the filestore
            print("Step 2: Copying filestore...")
            source_workspace = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            target_workspace = os.path.join(settings.BASE_DIR, 'instances', new_name)
            
            if os.path.exists(source_workspace):
                import shutil
                shutil.copytree(source_workspace, target_workspace)
                print(f"Filestore copied from {source_workspace} to {target_workspace}")
            
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
            
            print(f"Successfully copied instance {instance.name} to {new_name}")
            return new_instance
            
        except Exception as e:
            print(f"Error during instance copy: {str(e)}")
            new_instance.status = Instance.Status.ERROR
            new_instance.save()
            raise e

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
            from .backup_models import Backup
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
                
                # Read metadata
                metadata_path = os.path.join(temp_dir, 'metadata.json')
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                print(f"Backup metadata: {metadata}")
                
                # 1. Restore database
                print("Restoring database...")
                db_container = self.client.containers.get(f"db_{instance.name}")
                
                # Read dump file
                dump_path = os.path.join(temp_dir, 'database.dump')
                with open(dump_path, 'rb') as f:
                    dump_data = f.read()
                
                # Create tar archive for docker
                import tarfile
                import io
                tar_stream = io.BytesIO()
                tar = tarfile.open(fileobj=tar_stream, mode='w')
                tarinfo = tarfile.TarInfo(name='restore.dump')
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
                
                # Drop and recreate the database
                print(f"Dropping and recreating database '{odoo_db_name}'...")
                drop_result = db_container.exec_run(
                    f'psql -U odoo -c "DROP DATABASE IF EXISTS \\"{odoo_db_name}\\""',
                    environment={"PGPASSWORD": "odoo", "PGDATABASE": "postgres"}
                )
                print(f"Drop database result: {drop_result.exit_code} - {drop_result.output.decode()}")
                
                create_result = db_container.exec_run(
                    f'psql -U odoo -c "CREATE DATABASE \\"{odoo_db_name}\\""',
                    environment={"PGPASSWORD": "odoo", "PGDATABASE": "postgres"}
                )
                print(f"Create database result: {create_result.exit_code} - {create_result.output.decode()}")
                
                # Restore dump to the database (without -c flag to avoid clean errors)
                restore_result = db_container.exec_run(
                    f"pg_restore -U odoo -d {odoo_db_name} --no-owner --no-acl /tmp/restore.dump",
                    environment={"PGPASSWORD": "odoo"}
                )
                print(f"Database restore completed. Exit code: {restore_result.exit_code}")
                if restore_result.output:
                    print(f"Restore output: {restore_result.output.decode()}")
                
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
                        
                        # If there's a single subdirectory, use that as the actual filestore
                        if len(filestore_contents) == 1 and os.path.isdir(os.path.join(filestore_dir, filestore_contents[0])):
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
                        odoo_container.exec_run(f"mkdir -p {filestore_path}")
                        
                        # Put filestore archive in container to the correct database folder
                        print(f"Uploading filestore to container...")
                        odoo_container.put_archive(filestore_path, tar_stream.read())
                        
                        # Verify files were copied
                        verify_result = odoo_container.exec_run(f"ls -la {filestore_path}")
                        print(f"Files in container after restore: {verify_result.output.decode('utf-8')}")
                        
                        # Set correct ownership
                        print(f"Setting ownership...")
                        odoo_container.exec_run(f"chown -R odoo:odoo {filestore_path}")
                        
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


class SSLService:
    """Service for managing SSL certificates with Let's Encrypt"""
    
    @staticmethod
    def is_certbot_installed():
        """Check if certbot is installed"""
        import subprocess
        try:
            result = subprocess.run(['which', 'certbot'], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def install_certbot():
        """Install certbot based on the operating system"""
        import subprocess
        import platform
        
        system = platform.system()
        
        try:
            if system == "Darwin":  # macOS
                subprocess.run(['brew', 'install', 'certbot'], check=True)
            elif system == "Linux":
                # Try apt-get first (Debian/Ubuntu)
                try:
                    subprocess.run(['sudo', 'apt-get', 'update'], check=True)
                    subprocess.run(['sudo', 'apt-get', 'install', '-y', 'certbot'], check=True)
                except subprocess.CalledProcessError:
                    # Try yum (RHEL/CentOS)
                    subprocess.run(['sudo', 'yum', 'install', '-y', 'certbot'], check=True)
            else:
                raise Exception(f"Unsupported operating system: {system}")
            return True
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to install certbot: {str(e)}")
    
    @staticmethod
    def generate_certificate(domain, email):
        """
        Generate SSL certificate using Let's Encrypt
        Returns tuple: (certificate_path, key_path, success, message)
        """
        import subprocess
        import os
        
        # Check if certbot is installed
        if not SSLService.is_certbot_installed():
            try:
                SSLService.install_certbot()
            except Exception as e:
                return None, None, False, f"Certbot no está instalado y falló la instalación automática: {str(e)}"
        
        # Validate domain
        if not domain or '.' not in domain:
            return None, None, False, "Dominio inválido. Debe ser un dominio válido (ej: ejemplo.com)"
        
        # Validate email
        if not email or '@' not in email:
            return None, None, False, "Email inválido. Se requiere un email válido para Let's Encrypt"
        
        try:
            # Use certbot standalone mode to generate certificate
            # This requires port 80 to be available
            cmd = [
                'sudo', 'certbot', 'certonly',
                '--standalone',
                '--non-interactive',
                '--agree-tos',
                '--email', email,
                '-d', domain
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # Certificates are stored in /etc/letsencrypt/live/domain/
                cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
                key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"
                
                # Verify files exist
                if os.path.exists(cert_path) and os.path.exists(key_path):
                    return cert_path, key_path, True, "Certificado SSL generado exitosamente"
                else:
                    return None, None, False, "Certificado generado pero no se encontraron los archivos"
            else:
                error_msg = result.stderr or result.stdout
                return None, None, False, f"Error al generar certificado: {error_msg}"
                
        except subprocess.CalledProcessError as e:
            return None, None, False, f"Error ejecutando certbot: {str(e)}"
        except Exception as e:
            return None, None, False, f"Error inesperado: {str(e)}"
    
    @staticmethod
    def renew_certificate(domain):
        """Renew an existing SSL certificate"""
        import subprocess
        
        try:
            cmd = ['sudo', 'certbot', 'renew', '--cert-name', domain]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                return True, "Certificado renovado exitosamente"
            else:
                return False, f"Error al renovar certificado: {result.stderr or result.stdout}"
        except Exception as e:
            return False, f"Error al renovar certificado: {str(e)}"
    
    @staticmethod
    def check_certificate_expiry(cert_path):
        """Check when a certificate expires"""
        import subprocess
        from datetime import datetime
        
        try:
            cmd = ['openssl', 'x509', '-enddate', '-noout', '-in', cert_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Parse output: notAfter=Jan 1 00:00:00 2025 GMT
            date_str = result.stdout.strip().replace('notAfter=', '')
            expiry_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
            
            days_remaining = (expiry_date - datetime.now()).days
            return days_remaining, expiry_date
        except Exception as e:
            return None, None


class OdooModuleService:
    """Service for installing Odoo modules from ZIP files"""
    
    @staticmethod
    def install_module_from_zip(instance, zip_file):
        """
        Installs a module from an uploaded ZIP file by adding it to GitHub repo.
        
        Args:
            instance: Instance object
            zip_file: Uploaded ZIP file (Django UploadedFile)
            
        Returns:
            tuple: (success: bool, message: str, module_name: str or None)
        """
        import zipfile
        import tempfile
        
        try:
            # 1. Verify instance has GitHub repo configured
            if not instance.github_repo:
                return False, "Esta instancia no tiene un repositorio de GitHub configurado", None
            
            # 2. Save uploaded file to temporary location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
                for chunk in zip_file.chunks():
                    tmp_file.write(chunk)
                tmp_zip_path = tmp_file.name
            
            # 3. Extract to temporary directory first
            temp_extract_path = tempfile.mkdtemp()
            print(f"Extrayendo módulo temporalmente en: {temp_extract_path}")
            
            with zipfile.ZipFile(tmp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_path)
            
            # Clean up zip file
            os.unlink(tmp_zip_path)
            
            # 4. Find the actual module directory name
            extracted_module_name = None
            module_temp_path = None
            
            for item in os.listdir(temp_extract_path):
                item_path = os.path.join(temp_extract_path, item)
                if os.path.isdir(item_path):
                    if os.path.exists(os.path.join(item_path, '__manifest__.py')) or \
                       os.path.exists(os.path.join(item_path, '__openerp__.py')):
                        extracted_module_name = item
                        module_temp_path = item_path
                        break
            
            if not extracted_module_name:
                import shutil
                shutil.rmtree(temp_extract_path)
                return False, "No se pudo identificar el módulo en el ZIP. Asegúrate de que contiene __manifest__.py", None
            
            # 5. Copy module to GitHub repo addons directory
            workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name)
            addons_path = os.path.join(workspace_path, 'addons')
            os.makedirs(addons_path, exist_ok=True)
            
            module_dest_path = os.path.join(addons_path, extracted_module_name)
            
            # Copy module to repo
            import shutil
            if os.path.exists(module_dest_path):
                shutil.rmtree(module_dest_path)
            shutil.copytree(module_temp_path, module_dest_path)
            
            # Clean up temp directory
            shutil.rmtree(temp_extract_path)
            
            print(f"Módulo copiado a: {module_dest_path}")
            
            # 6. Commit and push to GitHub
            try:
                repo = git.Repo(workspace_path)
                
                # Add the new module
                repo.index.add([os.path.join('addons', extracted_module_name)])
                
                # Commit
                commit_message = f"Add module {extracted_module_name}"
                repo.index.commit(commit_message)
                
                # Push to remote
                origin = repo.remote(name='origin')
                origin.push()
                
                print(f"Módulo {extracted_module_name} agregado al repositorio y pusheado")
                
            except Exception as e:
                print(f"Error en Git: {str(e)}")
                return False, f"Error al hacer commit/push al repositorio: {str(e)}", extracted_module_name
            
            # 7. Deploy/upgrade the instance (this will update all modules)
            docker_service = DockerService()
            try:
                docker_service.deploy_instance(instance)
                
                return True, f"Módulo '{extracted_module_name}' agregado al repositorio y desplegado exitosamente", extracted_module_name
                
            except Exception as e:
                return False, f"Módulo agregado al repo pero error en deploy: {str(e)}", extracted_module_name
            
        except zipfile.BadZipFile:
            return False, "El archivo no es un ZIP válido", None
        except Exception as e:
            return False, f"Error inesperado: {str(e)}", None
