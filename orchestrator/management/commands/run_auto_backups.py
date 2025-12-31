from django.core.management.base import BaseCommand
from django.utils import timezone
from orchestrator.models import Instance
from orchestrator.config_models import GitHubConfig
from orchestrator.services import DockerService
from orchestrator.backup_models import Backup
import os

class Command(BaseCommand):
    help = 'Runs automatic backups based on system configuration'

    def handle(self, *args, **options):
        # 1. Find configurations with backup enabled
        configs = GitHubConfig.objects.filter(auto_backup_enabled=True)
        
        if not configs.exists():
            self.stdout.write(self.style.SUCCESS('No active backup configurations found.'))
            return

        now = timezone.now()
        
        for config in configs:
            unit = config.auto_backup_frequency_unit
            value = config.auto_backup_frequency_value
            retention = config.auto_backup_retention
            
            should_run = False
            
            # Logic assuming this command is run every 5 minutes
            if unit == 'minute':
                # Run every time (every 5 minutes or whatever the loop is)
                should_run = True
            elif unit == 'hour':
                # Run if we are close to the top of the hour
                if now.minute < 5:
                    should_run = True
                    # Optional: check value (e.g. every 2 hours)
                    # if now.hour % value != 0: should_run = False
            elif unit == 'day':
                # Run at midnight (approx)
                if now.hour == 0 and now.minute < 5:
                    should_run = True
            elif unit == 'week':
                # Run on Monday midnight
                if now.weekday() == 0 and now.hour == 0 and now.minute < 5:
                    should_run = True
            
            if should_run:
                self.stdout.write(f"Running {unit} backup task (every {value} {unit}s) for config {config}...")
                self.perform_backups(retention)
            else:
                 self.stdout.write(f"Skipping {unit} backup task (not time yet).")

    def perform_backups(self, retention):
        service = DockerService()
        instances = Instance.objects.filter(status='running') # Only backup running instances? or all? Usually active ones.
        # Maybe backup all valid instances regardless of status, but 'running' is safer for db consistency if we stop/start.
        # Actually backup_instance handles logic.
        instances = Instance.objects.all()

        for instance in instances:
            self.stdout.write(f"Backing up instance: {instance.name}")
            try:
                # Create backup
                backup = service.backup_instance(instance, include_filestore=True)
                self.stdout.write(self.style.SUCCESS(f"  - Backup created: {backup.filename}"))
                
                # Cleanup old backups
                self.cleanup_backups(instance, retention)
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Failed to backup {instance.name}: {str(e)}"))

    def cleanup_backups(self, instance, retention):
        backups = Backup.objects.filter(instance=instance).order_by('-created_at')
        if backups.count() > retention:
            to_delete = backups[retention:]
            for backup in to_delete:
                try:
                    if os.path.exists(backup.file_path):
                        os.remove(backup.file_path)
                    backup.delete()
                    self.stdout.write(f"  - Pruned old backup: {backup.filename}")
                except Exception as e:
                     self.stdout.write(self.style.WARNING(f"  - Failed to prune backup {backup.filename}: {str(e)}"))
