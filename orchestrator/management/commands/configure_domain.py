from django.core.management.base import BaseCommand

from orchestrator.traefik_service import TraefikService


class Command(BaseCommand):
    help = 'Write the Traefik routes (and HTTPS) for the panel and every instance from MAIN_DOMAIN or Settings.'

    def handle(self, *args, **options):
        for message in TraefikService.configure_all():
            self.stdout.write(message)
