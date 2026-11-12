import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from orchestrator.tasks import claim_next_task, recover_interrupted_tasks, run_task

SCHEDULE_CHECK_SECONDS = 60


class Command(BaseCommand):
    help = 'Process queued tasks (deploys, backups, restores) and run the schedules (backups, daily repository update). Run a single worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process pending tasks and exit')
        parser.add_argument('--poll-interval', type=float, default=2.0, help='Seconds between queue checks')
        parser.add_argument('--only', action='append', default=[], metavar='KIND',
                            help='Run only tasks of this kind (repeatable); such a worker skips the schedules')
        parser.add_argument('--exclude', action='append', default=[], metavar='KIND',
                            help='Leave tasks of this kind to another worker (repeatable)')

    def handle(self, *args, **options):
        only, exclude = options['only'], options['exclude']
        recovered = recover_interrupted_tasks(only, exclude)
        if recovered:
            self.stdout.write(self.style.WARNING(f'Marked {recovered} interrupted task(s) as failed'))

        last_schedule_check = None
        while True:
            # Inside a transaction (tests) the connection is not the worker's to close
            if not connection.in_atomic_block:
                close_old_connections()

            if not options['once'] and not only and (
                last_schedule_check is None or time.monotonic() - last_schedule_check >= SCHEDULE_CHECK_SECONDS
            ):
                last_schedule_check = time.monotonic()
                try:
                    call_command('run_auto_backups', stdout=self.stdout)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Scheduled backups failed: {e}'))
                try:
                    from orchestrator.services.metrics import record_sample
                    record_sample()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Metrics sample failed: {e}'))
                try:
                    from orchestrator.services.docker_service import DockerService
                    changed = DockerService().sync_published_ports()
                    if changed:
                        self.stdout.write(f"Updated the published port of: {', '.join(changed)}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Port sync failed: {e}'))
                try:
                    from orchestrator.services.docker_service import DockerService
                    capped = DockerService().apply_memory_limits()
                    if capped:
                        self.stdout.write(f"Memory limit applied to: {', '.join(capped)}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Memory limits failed: {e}'))
                try:
                    from orchestrator.services.webhooks import queue_daily_updates
                    queued = queue_daily_updates()
                    if queued:
                        self.stdout.write(f"Daily repository update queued for: {', '.join(queued)}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Daily repository update failed: {e}'))
                try:
                    from orchestrator.services.offsite import queue_daily_panel_backup, queue_weekly_verification
                    queue_daily_panel_backup()
                    queue_weekly_verification()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Panel backup failed: {e}'))
                try:
                    from orchestrator.services.power import apply_schedules, check_idle
                    for note in apply_schedules() + check_idle():
                        self.stdout.write(note)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Schedules failed: {e}'))
                try:
                    from orchestrator.services.health import check_instances
                    for name, state in check_instances():
                        self.stdout.write(f'Health: {name} is {state}')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Health check failed: {e}'))
                try:
                    from django.core.cache import cache
                    from orchestrator.services import alerts
                    alerts.check_server_usage()
                    alerts.monthly_usage_report()
                    if cache.add('certificate-check-run', 1, 3600):
                        alerts.check_certificates()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Alert checks failed: {e}'))
                try:
                    from orchestrator.services.trials import expire_demos
                    for line in expire_demos():
                        self.stdout.write(line)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Demo expiry failed: {e}'))

            task = claim_next_task(only, exclude)
            if task is not None:
                self.stdout.write(f'Running task {task.pk} ({task.kind})...')
                run_task(task)
                self.stdout.write(f'Task {task.pk}: {task.status}')
                continue

            if options['once']:
                return
            time.sleep(options['poll_interval'])
