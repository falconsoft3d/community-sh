import os
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone

LEGACY_ALIAS = 'legacy_sqlite'


class Command(BaseCommand):
    help = (
        'Copy data from the legacy db.sqlite3 into the configured database (DATABASE_URL). '
        'Runs only when the target database has no users yet, so it is safe on every start.'
    )

    def handle(self, *args, **options):
        if LEGACY_ALIAS not in settings.DATABASES:
            self.stdout.write('No legacy SQLite database to import.')
            return

        if User.objects.exists():
            self.stdout.write('Target database already has data; skipping SQLite import.')
            return

        legacy = connections[LEGACY_ALIAS]
        if 'auth_user' not in legacy.introspection.table_names() or not User.objects.using(LEGACY_ALIAS).exists():
            self.stdout.write('Legacy SQLite database is empty; nothing to import.')
            return

        sqlite_path = str(settings.DATABASES[LEGACY_ALIAS]['NAME'])
        backup_path = f"{sqlite_path}.pre-migration-{timezone.now():%Y%m%d%H%M%S}.bak"
        shutil.copy2(sqlite_path, backup_path)
        self.stdout.write(f'Backed up {sqlite_path} to {backup_path}')

        # Bring the legacy schema up to date so it matches the current models
        call_command('migrate', database=LEGACY_ALIAS, interactive=False, verbosity=0)

        with tempfile.TemporaryDirectory() as tmp_dir:
            dump_path = os.path.join(tmp_dir, 'legacy.json')
            call_command(
                'dumpdata',
                database=LEGACY_ALIAS,
                natural_foreign=True,
                natural_primary=True,
                exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'],
                output=dump_path,
                verbosity=0,
            )
            call_command('loaddata', dump_path, verbosity=1)

        self.stdout.write(self.style.SUCCESS(
            f'Imported data from {sqlite_path}. The SQLite file is no longer used and can be archived.'
        ))
