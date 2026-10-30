"""
Platform domain: the panel answers at MAIN_DOMAIN and each instance at
<client>-<version>-<name>.MAIN_DOMAIN (one label, so a single *.MAIN_DOMAIN DNS record
covers them all). Traefik issues the Let's Encrypt certificates when the installer
configured LETSENCRYPT_EMAIL.
"""
import json
import os
import re
import time

import docker
from django.utils.text import slugify

ACME_RESOLVER = 'letsencrypt'
ACME_STORAGE = '/opt/community-sh/letsencrypt/acme.json'
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


def _issued_hosts():
    """The hosts with a certificate in the storage of Traefik (only the names: it also holds the private keys)."""
    with open(ACME_STORAGE) as storage:
        resolvers = json.load(storage)
    hosts = set()
    for resolver in resolvers.values():
        for certificate in resolver.get('Certificates') or []:
            domain = certificate.get('domain') or {}
            hosts.add(domain.get('main'))
            hosts.update(domain.get('sans') or [])
    return hosts


def _traefik_log():
    containers = docker.from_env().containers.list(filters={'label': 'com.docker.compose.service=traefik'})
    return containers[0].logs(tail=3000).decode(errors='replace') if containers else ''


def certificate_problem(instance):
    """Why the hosts of the instance have no certificate yet: {'hosts', 'kind', 'retry_after'}, or None if they do.
    ``kind``: rate_limit (of Let's Encrypt), failed (its checks of the host failed), error, or None (nothing logged)."""
    if not acme_enabled() or instance.ssl_enabled or instance.status == instance.Status.STOPPED:
        return None
    try:
        issued = _issued_hosts()
    except (OSError, ValueError):
        return None
    missing = [host for host in instance_hosts(instance)
               if host not in issued and f"*.{host.split('.', 1)[-1]}" not in issued]
    if not missing:
        return None
    problem = {'hosts': missing, 'kind': None, 'retry_after': None}
    try:
        log = _traefik_log()
    except docker.errors.DockerException:
        return problem
    errors = [line for line in log.splitlines() if 'Unable to obtain ACME' in line and missing[0] in line]
    if errors:
        retry = re.search(r'retry after (\S+ \d+:\d+)', errors[-1])
        problem['retry_after'] = retry.group(1) if retry else None
        if 'too many certificates' in errors[-1]:
            problem['kind'] = 'rate_limit'
        elif 'too many failed authorizations' in errors[-1]:
            problem['kind'] = 'failed'
        else:
            problem['kind'] = 'error'
    return problem


def instance_hosts(instance):
    """Every host name Traefik routes to the instance."""
    hosts = []
    if instance.custom_domain:
        hosts += [instance.custom_domain, f'www.{instance.custom_domain}']
    domain = main_domain()
    if domain and instance.subdomain:
        hosts.append(f'{instance.subdomain}.{domain}')
    return hosts
