import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from orchestrator.tasks import claim_next_task, recover_interrupted_tasks, run_task

SCHEDULE_CHECK_SECONDS = 60


class Command(BaseCommand):
    help = 'Process queued tasks (deploys, backups, restores) and run scheduled backups. Run a single worker.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process pending tasks and exit')
        parser.add_argument('--poll-interval', type=float, default=2.0, help='Seconds between queue checks')

    def handle(self, *args, **options):
        recovered = recover_interrupted_tasks()
        if recovered:
            self.stdout.write(self.style.WARNING(f'Marked {recovered} interrupted task(s) as failed'))

        last_schedule_check = None
        while True:
            close_old_connections()

            if not options['once'] and (
                last_schedule_check is None or time.monotonic() - last_schedule_check >= SCHEDULE_CHECK_SECONDS
            ):
                last_schedule_check = time.monotonic()
                try:
                    call_command('run_auto_backups', stdout=self.stdout)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Scheduled backups failed: {e}'))

            task = claim_next_task()
            if task is not None:
                self.stdout.write(f'Running task {task.pk} ({task.kind})...')
                run_task(task)
                self.stdout.write(f'Task {task.pk}: {task.status}')
                continue

            if options['once']:
                return
            time.sleep(options['poll_interval'])
