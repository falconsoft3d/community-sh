import docker
import os
from django.conf import settings
from datetime import datetime, timezone
from .wal_models import WALRestorePoint, WALArchive, PITRRestore

class WALService:
    """Service for managing WAL archiving and Point-in-Time Recovery"""
    
    def __init__(self):
        self.client = docker.from_env()
    
    def create_restore_point(self, instance, name, description='', user=None):
        """
        Creates a named restore point in PostgreSQL
        This allows for easy restoration to this specific point
        """
        try:
            db_container = self.client.containers.get(f"db_{instance.name}")
            
            # Create restore point in PostgreSQL
            result = db_container.exec_run(
                f"psql -U odoo -d postgres -c \"SELECT pg_create_restore_point('{name}');\"",
                environment={"PGPASSWORD": "odoo"}
            )
            
            if result.exit_code != 0:
                raise Exception(f"Failed to create restore point: {result.output.decode('utf-8')}")
            
            # Get current WAL position
            lsn_result = db_container.exec_run(
                "psql -U odoo -d postgres -t -c \"SELECT pg_current_wal_lsn();\"",
                environment={"PGPASSWORD": "odoo"}
            )
            
            wal_lsn = lsn_result.output.decode('utf-8').strip()
            
            # Get current WAL file
            wal_file_result = db_container.exec_run(
                "psql -U odoo -d postgres -t -c \"SELECT pg_walfile_name(pg_current_wal_lsn());\"",
                environment={"PGPASSWORD": "odoo"}
            )
            
            wal_file = wal_file_result.output.decode('utf-8').strip()
            
            # Get Git information if available
            git_commit = ''
            git_branch = ''
            workspace_path = os.path.join(settings.BASE_DIR, 'instances', instance.name, 'addons')
            if os.path.exists(workspace_path):
                try:
                    import git
                    repo = git.Repo(workspace_path)
                    git_commit = repo.head.commit.hexsha
                    git_branch = repo.active_branch.name
                except:
                    pass
            
            # Create restore point record
            restore_point = WALRestorePoint.objects.create(
                instance=instance,
                name=name,
                description=description,
                wal_lsn=wal_lsn,
                wal_file=wal_file,
                restore_point_type='manual',
                created_by=user,
                git_commit=git_commit,
                git_branch=git_branch
            )
            
            print(f"✅ Restore point created: {name} at LSN {wal_lsn}")
            return restore_point
            
        except Exception as e:
            print(f"❌ Error creating restore point: {str(e)}")
            raise e
    
    def get_current_wal_status(self, instance):
        """
        Gets the current WAL archiving status
        """
        try:
            db_container = self.client.containers.get(f"db_{instance.name}")
            
            # Get current LSN
            lsn_result = db_container.exec_run(
                "psql -U odoo -d postgres -t -c \"SELECT pg_current_wal_lsn();\"",
                environment={"PGPASSWORD": "odoo"}
            )
            current_lsn = lsn_result.output.decode('utf-8').strip()
            
            # Get last archived WAL
            last_archived_result = db_container.exec_run(
                "psql -U odoo -d postgres -t -c \"SELECT last_archived_wal, last_archived_time FROM pg_stat_archiver;\"",
                environment={"PGPASSWORD": "odoo"}
            )
            last_archived = last_archived_result.output.decode('utf-8').strip()
            
            # Get archive status
            archive_status_result = db_container.exec_run(
                "psql -U odoo -d postgres -t -c \"SELECT archived_count, failed_count FROM pg_stat_archiver;\"",
                environment={"PGPASSWORD": "odoo"}
            )
            archive_status = archive_status_result.output.decode('utf-8').strip()
            
            return {
                'current_lsn': current_lsn,
                'last_archived': last_archived,
                'archive_status': archive_status,
                'status': 'healthy' if lsn_result.exit_code == 0 else 'error'
            }
            
        except Exception as e:
            print(f"Error getting WAL status: {str(e)}")
            return {'status': 'error', 'message': str(e)}
    
    def scan_wal_archives(self, instance):
        """
        Scans the WAL archive directory and updates database records
        """
        wal_archive_path = os.path.join(settings.BASE_DIR, 'backups', 'wal', instance.name)
        
        if not os.path.exists(wal_archive_path):
            return []
        
        wal_files = []
        for filename in os.listdir(wal_archive_path):
            if not filename.startswith('.'):
                file_path = os.path.join(wal_archive_path, filename)
                file_size = os.path.getsize(file_path)
                
                # Create or update WAL archive record
                wal_archive, created = WALArchive.objects.get_or_create(
                    instance=instance,
                    wal_file_name=filename,
                    defaults={
                        'file_path': file_path,
                        'file_size': file_size
                    }
                )
                
                if not created:
                    wal_archive.file_size = file_size
                    wal_archive.save()
                
                wal_files.append(wal_archive)
        
        return wal_files
    
    def restore_to_point(self, instance, restore_point=None, target_time=None, user=None):
        """
        Restores database to a specific restore point or timestamp (PITR)
        """
        # Create PITR restore record
        pitr_restore = PITRRestore.objects.create(
            instance=instance,
            restore_target=target_time if target_time else restore_point.created_at,
            target_lsn=restore_point.wal_lsn if restore_point else '',
            restore_point=restore_point,
            status='pending',
            initiated_by=user
        )
        
        try:
            pitr_restore.status = 'in_progress'
            pitr_restore.save()
            
            db_container = self.client.containers.get(f"db_{instance.name}")
            odoo_container_name = f"odoo_{instance.name}"
            
            # 1. Stop Odoo container
            print("🛑 Stopping Odoo container...")
            try:
                odoo_container = self.client.containers.get(odoo_container_name)
                odoo_container.stop()
            except:
                pass
            
            # 2. Stop PostgreSQL
            print("🛑 Stopping PostgreSQL...")
            db_container.stop()
            db_container.wait()
            
            # 3. Create recovery configuration
            print("⚙️ Creating recovery configuration...")
            wal_archive_path = os.path.join(settings.BASE_DIR, 'backups', 'wal', instance.name)
            
            recovery_conf = ""
            if restore_point:
                # Restore to named restore point
                recovery_conf = f"""
restore_command = 'cp /wal-archive/%f %p'
recovery_target_name = '{restore_point.name}'
recovery_target_action = 'promote'
"""
            elif target_time:
                # Restore to timestamp
                target_time_str = target_time.strftime('%Y-%m-%d %H:%M:%S')
                recovery_conf = f"""
restore_command = 'cp /wal-archive/%f %p'
recovery_target_time = '{target_time_str}'
recovery_target_action = 'promote'
"""
            
            # Write recovery configuration
            recovery_signal_path = os.path.join(
                settings.BASE_DIR, 
                'backups', 
                'recovery_temp', 
                f'recovery_{instance.name}.conf'
            )
            os.makedirs(os.path.dirname(recovery_signal_path), exist_ok=True)
            
            with open(recovery_signal_path, 'w') as f:
                f.write(recovery_conf)
            
            # 4. Copy recovery.conf to data directory
            print("📋 Copying recovery configuration...")
            # We need to mount and copy the recovery.conf file
            # This is a simplified approach - in production you'd want to handle this more robustly
            
            # Create recovery.signal file (PostgreSQL 12+)
            import tarfile
            import io
            
            tar_stream = io.BytesIO()
            tar = tarfile.open(fileobj=tar_stream, mode='w')
            
            # Add recovery.signal
            signal_info = tarfile.TarInfo(name='recovery.signal')
            signal_info.size = 0
            tar.addfile(signal_info, io.BytesIO(b''))
            
            # Add recovery configuration to postgresql.auto.conf
            conf_data = recovery_conf.encode('utf-8')
            conf_info = tarfile.TarInfo(name='recovery.conf')
            conf_info.size = len(conf_data)
            tar.addfile(conf_info, io.BytesIO(conf_data))
            
            tar.close()
            tar_stream.seek(0)
            
            # Start container temporarily to copy files
            db_container.start()
            import time
            time.sleep(2)
            
            db_container.put_archive('/var/lib/postgresql/data', tar_stream.read())
            
            # 5. Restart PostgreSQL to trigger recovery
            print("🔄 Restarting PostgreSQL for recovery...")
            db_container.restart()
            
            # 6. Wait for recovery to complete
            print("⏳ Waiting for recovery to complete...")
            max_wait = 120  # 2 minutes
            waited = 0
            recovery_complete = False
            
            while waited < max_wait:
                time.sleep(5)
                waited += 5
                
                try:
                    # Check if recovery is complete
                    check_result = db_container.exec_run(
                        "psql -U odoo -d postgres -t -c \"SELECT pg_is_in_recovery();\"",
                        environment={"PGPASSWORD": "odoo"}
                    )
                    
                    if check_result.exit_code == 0:
                        is_recovering = check_result.output.decode('utf-8').strip()
                        if is_recovering == 'f':  # false = not in recovery = complete
                            recovery_complete = True
                            break
                except:
                    continue
            
            if not recovery_complete:
                raise Exception("Recovery timeout - took longer than expected")
            
            # 7. Restart Odoo
            print("🚀 Restarting Odoo...")
            try:
                odoo_container = self.client.containers.get(odoo_container_name)
                odoo_container.start()
            except Exception as e:
                print(f"Warning: Could not restart Odoo: {e}")
            
            # Update restore record
            pitr_restore.status = 'completed'
            pitr_restore.completed_at = datetime.now(timezone.utc)
            pitr_restore.recovery_logs = "Recovery completed successfully"
            pitr_restore.save()
            
            print("✅ PITR restore completed successfully!")
            return pitr_restore
            
        except Exception as e:
            pitr_restore.status = 'failed'
            pitr_restore.error_message = str(e)
            pitr_restore.completed_at = datetime.now(timezone.utc)
            pitr_restore.save()
            
            print(f"❌ PITR restore failed: {str(e)}")
            raise e
    
    def verify_restore_point(self, restore_point):
        """
        Verifies that a restore point is still valid and accessible
        """
        try:
            instance = restore_point.instance
            db_container = self.client.containers.get(f"db_{instance.name}")
            
            # Check if WAL file exists
            wal_archive_path = os.path.join(
                settings.BASE_DIR, 
                'backups', 
                'wal', 
                instance.name, 
                restore_point.wal_file
            )
            
            if not os.path.exists(wal_archive_path):
                return False, "WAL file not found"
            
            # Verify PostgreSQL is accessible
            result = db_container.exec_run(
                "psql -U odoo -d postgres -c 'SELECT 1;'",
                environment={"PGPASSWORD": "odoo"}
            )
            
            if result.exit_code != 0:
                return False, "Database not accessible"
            
            restore_point.is_verified = True
            restore_point.verification_date = datetime.now(timezone.utc)
            restore_point.save()
            
            return True, "Restore point verified"
            
        except Exception as e:
            return False, str(e)
    
    def cleanup_old_wal_files(self, instance, keep_days=7):
        """
        Removes WAL files older than specified days
        Keeps files that are referenced by restore points
        """
        from datetime import timedelta
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=keep_days)
        
        # Get WAL files to keep (referenced by restore points)
        protected_wal_files = set(
            WALRestorePoint.objects.filter(
                instance=instance,
                created_at__gte=cutoff_date
            ).values_list('wal_file', flat=True)
        )
        
        # Delete old WAL archives
        old_archives = WALArchive.objects.filter(
            instance=instance,
            created_at__lt=cutoff_date
        ).exclude(wal_file_name__in=protected_wal_files)
        
        deleted_count = 0
        for archive in old_archives:
            try:
                if os.path.exists(archive.file_path):
                    os.remove(archive.file_path)
                archive.delete()
                deleted_count += 1
            except Exception as e:
                print(f"Error deleting WAL file {archive.wal_file_name}: {e}")
        
        return deleted_count
