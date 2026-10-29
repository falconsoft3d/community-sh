from config.version import VERSION

from .permissions import is_client

# First part of the URL name -> sidebar section ("project-detail" -> "projects")
SECTIONS = {
    'project': 'projects', 'instance': 'instances', 'container': 'containers', 'metrics': 'metrics',
    'backup': 'backups', 'client': 'clients', 'user': 'users', 'change': 'users', 'settings': 'settings',
    'generate': 'settings', 'run': 'settings', 'about': 'about', 'docker': 'docker', 'todo': 'todo',
    'activity': 'activity',
}


DOCKER_COUNT_SECONDS = 30


def _docker_running():
    """Running containers on the host (cached: it's a Docker API call)."""
    from django.core.cache import cache
    count = cache.get('nav-docker-running')
    if count is None:
        try:
            import docker
            count = len(docker.from_env().containers.list())
        except Exception:
            count = ''
        cache.set('nav-docker-running', count, DOCKER_COUNT_SECONDS)
    return count


def nav_counts(user):
    """Sidebar badges, with the same visibility rules as each list."""
    from django.contrib.auth.models import User
    from .backup_models import Backup
    from .container_models import Container
    from .permissions import instances_for, projects_for
    from .todo_models import Todo
    from .views.todo import todos_for
    instances = instances_for(user)
    counts = {
        'projects': projects_for(user).count(),
        'instances': instances.count(),
        'backups': Backup.objects.filter(instance__in=instances).count(),
        'containers': Container.objects.filter(created_by=user).count(),
        'todo': todos_for(user).exclude(status=Todo.Status.DONE).count(),
    }
    from .task_models import Task
    from .views.activity import tasks_for
    # Activity: the tasks running or waiting now (no badge when there are none)
    counts['activity'] = tasks_for(user).filter(status__in=(Task.Status.PENDING, Task.Status.RUNNING)).count() or ''
    if user.is_superuser:
        counts['users'] = User.objects.count()
        counts['docker'] = _docker_running()
    return counts


def navigation(request):
    match = getattr(request, 'resolver_match', None)
    url_name = (match.url_name or '') if match else ''
    section = SECTIONS.get(url_name.split('-')[0], '')
    if url_name == 'instance-backups':
        section = 'backups'
    user = getattr(request, 'user', None)
    signed_in = bool(user and user.is_authenticated)
    return {
        'app_version': VERSION,
        'nav_section': section,
        'user_is_client': is_client(user) if user is not None else False,
        # Only the panel's own pages draw the sidebar
        'nav_counts': nav_counts(user) if signed_in and match and match.app_name != 'admin' else {},
    }
