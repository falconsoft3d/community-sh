"""
Platform domain: the panel answers at MAIN_DOMAIN and each instance at
<client>-<version>-<name>.MAIN_DOMAIN (one label, so a single *.MAIN_DOMAIN DNS record
covers them all). Traefik issues the Let's Encrypt certificates when the installer
configured LETSENCRYPT_EMAIL.
"""
import os
import time

from django.utils.text import slugify

ACME_RESOLVER = 'letsencrypt'
_CACHE_SECONDS = 10
_cache = {}


def main_domain():
    """The domain set in Settings, else the one the installer wrote to .env ('' when none)."""
    cached = _cache.get('main_domain')
    if cached and time.monotonic() - cached[1] < _CACHE_SECONDS:
        return cached[0]
    domain = ''
    try:
        from ..permissions import get_global_config
        config = get_global_config()
        domain = config.main_domain if config and config.main_domain else ''
    except Exception:
        pass  # database not ready yet
    domain = (domain or os.environ.get('MAIN_DOMAIN', '')).strip().lower()
    if domain == 'localhost':
        domain = ''
    _cache['main_domain'] = (domain, time.monotonic())
    return domain


def clear_cache():
    _cache.clear()


def acme_enabled():
    """Traefik requests certificates itself once the installer gave it an email."""
    return bool(os.environ.get('LETSENCRYPT_EMAIL', '').strip())


def build_subdomain(instance):
    """client-20-name: the project's client user (or the project name), the Odoo major version and the instance."""
    project = instance.project
    owner = ''
    if project is not None:
        owner = project.client.username if project.client_id else project.name
    parts = [slugify(owner), str(int(float(instance.odoo_version))), slugify(instance.name)]
    return '-'.join(part.replace('_', '-') for part in parts if part)[:63].strip('-')


def instance_hosts(instance):
    """Every host name Traefik routes to the instance."""
    hosts = []
    if instance.custom_domain:
        hosts += [instance.custom_domain, f'www.{instance.custom_domain}']
    domain = main_domain()
    if domain and instance.subdomain:
        hosts.append(f'{instance.subdomain}.{domain}')
    return hosts
