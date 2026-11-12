"""
Saving memory (the server is small): instances can stop on their own when nobody logs into their Odoo for a few
days (with an alert the day before) and follow a daily schedule (UTC) to start and stop. Both are off unless
chosen on the instance. The worker calls these every minute; each acts at most once per day and instance.
"""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone


def last_login(instance):
    """When someone last logged into any database of the instance (its login log), or None if unknown."""
    from datetime import datetime, timezone as tz
    from .docker_service import DockerService
    service = DockerService()
    db = service._get_container(f'db_{instance.name}')
    if db is None or db.status != 'running':
        return None
    latest = None
    for database in service._list_user_databases(db):
        value = service._psql(db, database, 'SELECT extract(epoch from max(create_date)) FROM res_users_log', check=False)
        if not value.replace('.', '', 1).isdigit():
            # Odoo versions without res_users_log keep it on the user
            value = service._psql(db, database, 'SELECT extract(epoch from max(login_date)) FROM res_users', check=False)
        if value.replace('.', '', 1).isdigit():
            moment = datetime.fromtimestamp(float(value), tz=tz.utc)
            latest = max(latest, moment) if latest else moment
    return latest


def check_idle(now=None):
    """Once a day: stop the instances with auto_stop_days nobody has used in that time. Returns notes."""
    from ..models import Instance
    from . import alerts
    from .docker_service import DockerService
    now = now or timezone.now()
    if not cache.add('idle-check-day', 1, 23 * 3600):
        return []
    notes = []
    for instance in Instance.objects.filter(status=Instance.Status.RUNNING, auto_stop_days__gt=0):
        since = last_login(instance) or instance.created_at
        idle = (now - since).days
        if idle >= instance.auto_stop_days:
            DockerService().stop_instance(instance)
            notes.append(f'{instance.name}: detenida tras {idle} días sin entrar nadie')
            alerts.alert(f'idle-stop:{instance.pk}', f'{instance.name} detenida por no usarse',
                         f'Nadie ha entrado en {instance.name} desde hace {idle} días: se ha detenido para ahorrar memoria '
                         f'(«Detener si nadie entra en {instance.auto_stop_days} días»). Arráncala con Restart cuando la necesites.',
                         cooldown=0)
        elif idle == instance.auto_stop_days - 1:
            alerts.alert(f'idle-warn:{instance.pk}', f'{instance.name} se detendrá mañana',
                         f'Nadie ha entrado en {instance.name} desde hace {idle} días: mañana se detendrá para ahorrar '
                         f'memoria si sigue sin usarse. Entra en su Odoo para mantenerla en marcha.', cooldown=20 * 3600)
    return notes


def apply_schedules(now=None):
    """Start or stop the instances whose schedule time has come today (UTC), once each. Returns notes."""
    from ..models import Instance
    from .docker_service import DockerService
    now = now or timezone.now()
    today = now.date().isoformat()
    notes = []
    for instance in Instance.objects.exclude(schedule_start=None, schedule_stop=None):
        for action, at in (('start', instance.schedule_start), ('stop', instance.schedule_stop)):
            # Within the hour after its time (the worker may be busy with a long task), once a day
            if at is None:
                continue
            due = timezone.datetime.combine(now.date(), at, tzinfo=now.tzinfo)
            if not timedelta(0) <= now - due < timedelta(hours=1):
                continue
            if not cache.add(f'schedule:{instance.pk}:{action}:{today}', 1, 26 * 3600):
                continue
            service = DockerService()
            if action == 'stop' and instance.status == Instance.Status.RUNNING:
                service.stop_instance(instance)
                notes.append(f'{instance.name}: detenida por su horario ({at:%H:%M} UTC)')
            elif action == 'start' and instance.status == Instance.Status.STOPPED:
                service.restart_instance(instance)
                notes.append(f'{instance.name}: arrancada por su horario ({at:%H:%M} UTC)')
    return notes
