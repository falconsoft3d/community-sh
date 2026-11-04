"""The Dashboard: the most important figures of the whole platform, each one linked to its page."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince


def _kpi(label, value, hint, icon, url, tone='default'):
    return {'label': label, 'value': value, 'hint': hint, 'icon': icon, 'url': url, 'tone': tone}


def _plural(count, word, plural=None):
    return f'{count} {word if count == 1 else (plural or word + "s")}'


def platform_kpis(user):
    """Groups of KPIs for this user (an administrator sees the whole server)."""
    from ..backup_models import Backup
    from ..container_models import Container
    from ..permissions import instances_for, projects_for
    from ..task_models import Task
    from ..todo_models import Todo
    from ..trial_models import TrialRequest
    from .trials import ACTIVE, demos_today, server_limits

    now = timezone.now()
    admin = user.is_superuser
    instances = instances_for(user)
    projects = projects_for(user)
    total, running = instances.count(), instances.filter(status='running').count()
    errors = instances.filter(status='error').count()
    containers = Container.objects.all() if admin else Container.objects.filter(created_by=user)
    containers_running = containers.filter(status='running').count()
    backups = Backup.objects.filter(instance__in=instances)
    last_backup = backups.order_by('-created_at').first()
    tasks = Task.objects.all() if admin else Task.objects.filter(instance__in=instances)
    working = tasks.filter(status__in=['pending', 'running']).count()
    failed = tasks.filter(status='failed', created_at__gte=now - timedelta(days=7)).count()

    groups = [{'title': 'Plataforma', 'kpis': [
        _kpi('Proyectos', projects.count(), _plural(projects.filter(trial_enabled=True).count(), 'en modo test', 'en modo test'),
             'folder-kanban', reverse('project-list')),
        _kpi('Instancias en marcha', f'{running}/{total}',
             _plural(errors, 'con error', 'con error') if errors else 'Ninguna con error',
             'server', reverse('instance-list'), 'red' if errors else ('green' if total and running == total else 'default')),
        _kpi('Contenedores en marcha', f'{containers_running}/{containers.count()}', 'Aplicaciones en Docker',
             'box', reverse('container-list')),
        _kpi('Copias de seguridad', backups.count(),
             f'Última hace {timesince(last_backup.created_at, now).split(",")[0]}' if last_backup else 'Ninguna todavía',
             'archive', reverse('backup-list'),
             'amber' if total and (last_backup is None or now - last_backup.created_at > timedelta(days=7)) else 'default'),
        _kpi('Tareas en curso', working, _plural(failed, 'fallida') + ' en 7 días' if failed else 'Sin fallos en 7 días',
             'activity', reverse('activity') + ('?status=failed' if failed else ''), 'red' if failed else 'default'),
    ]}]

    managed = projects if admin else projects.filter(owner=user)
    demos = TrialRequest.objects.filter(project__in=managed)
    if demos.exists() or managed.filter(trial_enabled=True).exists():
        per_day, at_once = server_limits()
        active = TrialRequest.objects.filter(ACTIVE).count() if admin else demos.filter(ACTIVE).count()
        month = demos.filter(created_at__gte=now - timedelta(days=30)).exclude(status=TrialRequest.Status.FAILED)
        expiring = demos.filter(status=TrialRequest.Status.READY, instance__isnull=False,
                                expires_at__lte=now + timedelta(days=3)).count()
        failed_demos = demos.filter(status=TrialRequest.Status.FAILED, created_at__gte=now - timedelta(days=30)).count()
        settings_demos = reverse('settings') + '#demos' if admin else reverse('project-list')
        from ..views.contacts import contacts_for
        contacts = contacts_for(user)
        today = demos_today()
        groups.append({'title': 'Demos', 'kpis': [
            _kpi('Demos activas', f'{active}/{at_once}', 'Funcionando ahora en el servidor', 'flask-conical',
                 settings_demos, 'amber' if active >= at_once else 'blue'),
            _kpi('Pedidas hoy', f'{today}/{per_day}', 'Límite diario de todo el servidor', 'calendar-check',
                 settings_demos, 'amber' if today >= per_day else 'default'),
            _kpi('Pedidas en 30 días', month.count(), _plural(month.exclude(emailed_at=None).count(), 'enviada') + ' por email',
                 'user-plus', reverse('activity') + '?kind=trial'),
            _kpi('Contactos', contacts.count(), _plural(contacts.filter(created_at__gte=now - timedelta(days=30)).count(), 'nuevo') + ' en 30 días',
                 'contact', reverse('contact-list'), 'blue'),
            _kpi('Vencen en 3 días', expiring, 'Se detienen al vencer y se eliminan 7 días después', 'hourglass',
                 reverse('project-list'), 'amber' if expiring else 'default'),
            _kpi('Demos fallidas (30 días)', failed_demos, 'Revisa su log en Actividad' if failed_demos else 'Ninguna',
                 'circle-alert', reverse('activity') + '?kind=trial&status=failed', 'red' if failed_demos else 'default'),
        ]})

    if admin:
        import psutil
        from ..metrics_models import MetricSample
        from ..permissions import get_global_config
        from django.contrib.auth.models import User
        sample = MetricSample.objects.order_by('-timestamp').first()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        config = get_global_config()
        users = User.objects.filter(is_active=True)
        without_2fa = users.exclude(profile__two_factor_enabled=True).count()
        pending_todos = Todo.objects.exclude(status='done').count()
        groups.append({'title': 'Servidor y seguridad', 'kpis': [
            _kpi('CPU', f'{sample.cpu_percent:.0f}%' if sample else '—', 'Última muestra del worker', 'cpu',
                 reverse('metrics'), 'red' if sample and sample.cpu_percent > 85 else 'default'),
            _kpi('Memoria', f'{memory.percent:.0f}%', f'{memory.available // 1024 ** 2} MB libres', 'memory-stick',
                 reverse('metrics'), 'red' if memory.percent > 90 else ('amber' if memory.percent > 75 else 'default')),
            _kpi('Disco', f'{disk.percent:.0f}%', f'{disk.free // 1024 ** 3} GB libres', 'hard-drive',
                 reverse('docker-overview'), 'red' if disk.percent > 90 else ('amber' if disk.percent > 80 else 'default')),
            _kpi('Usuarios sin 2FA', f'{without_2fa}/{users.count()}',
                 '2FA obligatorio' if config and config.two_factor_required else '2FA opcional', 'shield-alert',
                 reverse('user-list'), 'amber' if without_2fa and not (config and config.two_factor_required) else 'default'),
            _kpi('Correo saliente', 'Activo' if config and config.smtp_enabled and config.smtp_host else 'Apagado',
                 config.smtp_host if config and config.smtp_host else 'Sin servidor SMTP', 'mail',
                 reverse('settings') + '#email', 'green' if config and config.smtp_enabled and config.smtp_host else 'default'),
            _kpi('Todo pendiente', pending_todos, 'Tareas del equipo', 'list-todo', reverse('todo-list')),
        ]})
    return groups


def dashboard_lists(user):
    """The rows below the KPIs: demos about to expire, instances with errors and the latest tasks."""
    from ..permissions import instances_for, managed_projects_for
    from ..task_models import Task
    from ..trial_models import TrialRequest
    instances = instances_for(user)
    expiring = TrialRequest.objects.filter(project__in=managed_projects_for(user), status=TrialRequest.Status.READY,
                                           instance__isnull=False).select_related('instance', 'project').order_by('expires_at')[:5]
    broken = instances.filter(status='error').select_related('project')[:5]
    tasks = (Task.objects.all() if user.is_superuser else Task.objects.filter(instance__in=instances)) \
        .select_related('instance').order_by('-created_at')[:6]
    return {'expiring_demos': expiring, 'broken_instances': broken, 'recent_tasks': tasks}
