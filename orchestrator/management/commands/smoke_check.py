"""
After a deploy: open the panel's main pages as an administrator, against the real database, and fail if any
of them breaks (a 5xx or an exception). The login page answering isn't enough: on 2026-11-12 it answered 200
while every other page failed (code on disk without its migrations).

    python manage.py smoke_check        # exit code 1 if a page fails
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse

PAGES = ['dashboard', 'instance-list', 'project-list', 'backup-list', 'container-list', 'contact-list', 'todo-list',
         'activity', 'metrics', 'docker-overview', 'user-list', 'audit', 'settings', 'help', 'about']


class Command(BaseCommand):
    help = "Open the panel's main pages as an administrator and fail if any of them breaks"

    def handle(self, *args, **options):
        from orchestrator.models import Instance
        from orchestrator.project_models import Project
        admin = User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
        if admin is None:
            self.stdout.write('No administrator yet: nothing to check')
            return
        urls = [reverse(name) for name in PAGES]
        # One instance and one project too: their pages use most of the models
        instance = Instance.objects.order_by('-id').first()
        if instance:
            urls.append(reverse('instance-detail', args=[instance.pk]))
        project = Project.objects.order_by('-id').first()
        if project:
            urls.append(reverse('project-detail', args=[project.pk]))
        # 127.0.0.1 is always an allowed host; secure: no redirect to HTTPS
        client = Client(HTTP_HOST='127.0.0.1')
        client.force_login(admin)
        failures = []
        try:
            for url in urls:
                try:
                    status = client.get(url, secure=True).status_code
                except Exception as e:  # the test client raises what the view raised
                    failures.append(f'{url}: {type(e).__name__}: {e}'[:400])
                    continue
                if status >= 500:
                    failures.append(f'{url}: HTTP {status}')
                else:
                    self.stdout.write(f'  {status} {url}')
        finally:
            client.logout()  # the session it opened
        if failures:
            raise CommandError('Pages that fail:\n' + '\n'.join(failures))
        self.stdout.write(self.style.SUCCESS(f'{len(urls)} pages OK'))
