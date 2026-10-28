from config.version import VERSION

from .permissions import is_client

# First part of the URL name -> sidebar section ("project-detail" -> "projects")
SECTIONS = {
    'project': 'projects', 'instance': 'instances', 'container': 'containers', 'metrics': 'metrics',
    'backup': 'backups', 'client': 'clients', 'user': 'users', 'change': 'users', 'settings': 'settings',
    'generate': 'settings', 'run': 'settings', 'about': 'about', 'docker': 'docker',
}


def navigation(request):
    match = getattr(request, 'resolver_match', None)
    url_name = (match.url_name or '') if match else ''
    section = SECTIONS.get(url_name.split('-')[0], '')
    if url_name == 'instance-backups':
        section = 'backups'
    return {
        'app_version': VERSION,
        'nav_section': section,
        'user_is_client': is_client(request.user) if hasattr(request, 'user') else False,
    }
