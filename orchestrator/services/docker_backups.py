"""Backups of an instance (database and filestore) and restoring them. Part of DockerService."""
import os
from django.conf import settings
from ..task_log import progress
from .docker_helpers import (
    read_backup_metadata,
)


class BackupMixin:
    def backup_all_databases(self, instance, include_filestore=True, user=None):
        """The backups of the instance: one file per database when it has several (a file restores one database)."""
        databases = []
        db_container = None if instance.database_name else self._get_container(f'db_{instance.name}')
        if db_container is not None:
            databases = self._list_user_databases(db_container)
        if len(databases) < 2:
            return [self.backup_instance(instance, include_filestore, user)]
        return [self.backup_instance(instance, include_filestore, user, database=database) for database in databases]

    def backup_instance(self, instance, include_filestore=True, user=None, database=None):
        """
        Creates a backup of the instance (database + optionally filestore)
        Returns the Backup model instance
        """
        import zipfile
        from datetime import datetime
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{instance.name}{f'_{database}' if database else ''}_backup_{timestamp}.zip"
        
        # Create backups directory if it doesn't exist
        backups_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backups_dir, exist_ok=True)
        
        backup_path = os.path.join(backups_dir, backup_filename)
        
        print(f"Creating backup for instance {instance.name}...")
        
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Backup Odoo database
                progress(10, 'Copiando la base de datos')
                print(f"Backing up database for {instance.name}...")
                db_container = self.client.containers.get(f"db_{instance.name}")
                
                # Check if database_name is specified in instance
                if database:
                    odoo_db_name = database
                elif instance.database_name:
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
                    progress(55, 'Copiando los adjuntos (filestore)')
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
                
                progress(90, 'Guardando el archivo del respaldo')
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
                from .archives import GB, safe_extractall
                # Filestores compress little: far more than 100x the archive is a zip bomb
                limit = min(100 * GB, max(2 * GB, 100 * os.path.getsize(backup_file_path)))
                safe_extractall(zipf, temp_dir, max_bytes=limit, max_files=2_000_000)
                
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
                progress(15, 'Restaurando la base de datos')
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
                    progress(60, 'Restaurando los adjuntos (filestore)')
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
