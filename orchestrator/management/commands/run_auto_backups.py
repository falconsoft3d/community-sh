from django.core.management.base import BaseCommand
from django.utils import timezone
from orchestrator.models import Instance
from orchestrator.permissions import get_global_config
from orchestrator.services import DockerService
from orchestrator.backup_models import Backup
import os
from datetime import timedelta

UNIT_SECONDS = {'minute': 60, 'hour': 3600, 'day': 86400, 'week': 604800}


class Command(BaseCommand):
    help = 'Runs automatic backups based on system configuration'

    def handle(self, *args, **options):
        # Backups are configured platform-wide by the admin
        config = get_global_config()
        if not config or not config.auto_backup_enabled:
            self.stdout.write(self.style.SUCCESS('No active backup configuration found.'))
            return

        unit = config.auto_backup_frequency_unit
        value = max(config.auto_backup_frequency_value or 1, 1)
        interval = timedelta(seconds=UNIT_SECONDS.get(unit, UNIT_SECONDS['day']) * value)
        now = timezone.now()

        if config.last_auto_backup_at and now - config.last_auto_backup_at < interval:
            next_run = config.last_auto_backup_at + interval
            self.stdout.write(f"Skipping backup (every {value} {unit}s, next run at {next_run:%Y-%m-%d %H:%M} UTC).")
            return

        # Record the run before starting so a slow or failing run isn't retried every loop
        config.last_auto_backup_at = now
        config.save(update_fields=['last_auto_backup_at'])
        self.stdout.write(f"Running backup task (every {value} {unit}s)...")
        self.perform_backups(config.auto_backup_retention)

    def perform_backups(self, retention):
        service = DockerService()
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
