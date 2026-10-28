"""
The author's other projects, shown on the landing page: read from a TicketPro dynamic table
(TICKETPROO_API_URL, with the TICKETPROO_API_TOKEN from .env) on the server, cached.
"""
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = 'landing-my-projects'
CACHE_SECONDS = 15 * 60
MAX_PAGES = 10


def _fetch():
    projects, page = [], 1
    while page <= MAX_PAGES:
        response = requests.get(settings.TICKETPROO_API_URL, params={'page': page}, timeout=8,
                                headers={'X-API-Token': settings.TICKETPROO_API_TOKEN})
        response.raise_for_status()
        data = response.json()
        rows = data.get('data') or []
        projects += rows
        if not rows or len(projects) >= (data.get('total') or 0):
            break
        page += 1
    return projects


def _card(row):
    web = (row.get('web') or '').strip()
    url = web if web.startswith(('http://', 'https://')) else f'https://{web}' if web else ''
    name = (row.get('nombre') or web or '').strip()
    return {'name': name, 'url': url, 'host': web.split('//')[-1].strip('/'),
            'description': (row.get('descripcion') or '').strip()}


def my_projects(exclude_host=''):
    """Cards [{name, url, host, description}], newest first; [] if not configured or unreachable."""
    if not settings.TICKETPROO_API_TOKEN:
        return []
    projects = cache.get(CACHE_KEY)
    if projects is None:
        try:
            projects = [_card(row) for row in _fetch() if row.get('nombre') or row.get('web')]
        except (requests.RequestException, ValueError) as e:
            logger.warning('Could not read the projects list: %s', e)
            projects = []
            cache.set(CACHE_KEY, projects, 60)  # try again in a minute
            return projects
        cache.set(CACHE_KEY, projects, CACHE_SECONDS)
    exclude = exclude_host.lower().removeprefix('www.')
    return [p for p in projects if p['host'].lower().removeprefix('www.') != exclude]
