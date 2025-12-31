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
        configs = GitHubConfig.objects.exclude(auto_backup_frequency='none')
        
        if not configs.exists():
            self.stdout.write(self.style.SUCCESS('No active backup configurations found.'))
            return

        # Assuming system-wide single config usually, but handling multiple just in case
        # In a real scenario you might want to lock this to a specific admin user
        
        now = timezone.now()
        
        for config in configs:
            freq = config.auto_backup_frequency
            retention = config.auto_backup_retention
            
            should_run = False
            
            # Simple logic assuming this command is run every 5 minutes via cron
            if freq == 'minutes':
                # Run every time (every 5 minutes)
                should_run = True
            elif freq == 'hourly':
                should_run = True
            elif freq == 'daily':
                # Run at midnight (approx)
                if now.hour == 0:
                    should_run = True
            elif freq == 'weekly':
                # Run on Monday midnight
                if now.weekday() == 0 and now.hour == 0:
                    should_run = True
            
            if should_run:
                self.stdout.write(f"Running {freq} backup task for config {config}...")
                self.perform_backups(retention)
            else:
                 self.stdout.write(f"Skipping {freq} backup task (not time yet).")

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
