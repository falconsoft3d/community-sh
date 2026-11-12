"""
Alerts for whoever runs the platform: failed tasks, instances that stop answering (and come back), full disk or
memory and missing certificates. By email (the notification addresses of Settings → General, else the
administrators) through the SMTP server of Settings → Email, and to an optional webhook (Slack, Discord, Google
Chat, n8n...). The same alert isn't repeated within its cooldown.
"""
import json
import logging
import urllib.request

from django.core.cache import cache

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 6 * 3600
HIGH_USAGE_PERCENT = 90


def _recipients(config):
    from django.contrib.auth.models import User
    emails = [e.strip() for e in (config.notification_emails or '').split(',') if e.strip()]
    return emails or list(User.objects.filter(is_superuser=True, is_active=True).exclude(email='')
                          .values_list('email', flat=True))


def _post_webhook(url, subject, body):
    text = f'{subject}\n{body}'
    # "text": Slack, Google Chat, Mattermost, n8n...; "content": Discord (2000 characters at most)
    data = json.dumps({'text': text, 'content': text[:1900], 'subject': subject, 'body': body}).encode()
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json',
                                                              'User-Agent': 'Community-SH-alerts'})
    with urllib.request.urlopen(request, timeout=10):
        pass


def alert(key, subject, body, cooldown=COOLDOWN_SECONDS):
    """
    Send an alert unless the same key was sent within its cooldown (cooldown=0: always).
    Returns True when it went out by some channel. Never raises: an alert must not break what reports it.
    """
    from ..permissions import get_global_config
    from . import mail
    try:
        config = get_global_config()
        if config is None or not config.alerts_enabled:
            return False
        if cooldown and not cache.add(f'alert:{key}', 1, cooldown):
            return False
        subject = f'[Community SH] {subject}'
        sent = False
        recipients = _recipients(config)
        if recipients and mail.smtp_config() is not None:
            sent, error = mail.send(subject, f'{body}\n\n---\nAlerta automática de Community SH', recipients)
            if error:
                logger.warning('Alert email failed: %s', error)
        if config.alert_webhook_url:
            try:
                _post_webhook(config.alert_webhook_url, subject, body)
                sent = True
            except Exception as e:
                logger.warning('Alert webhook failed: %s', e)
        return sent
    except Exception:
        logger.exception('Alert %s failed', key)
        return False


def clear(key):
    """The condition is over: the next time it happens it is alerted again right away."""
    cache.delete(f'alert:{key}')


def task_failed(task):
    from ..task_models import Task
    if task.kind == Task.Kind.AI_CHAT:  # the person chatting already sees it
        return
    where = f' de {task.instance.name}' if task.instance_id else ''
    alert(f'task-failed:{task.pk}', f'Tarea fallida: {task.get_kind_display()}{where}',
          f'La tarea #{task.pk} ({task.get_kind_display()}{where}) ha fallado:\n\n{(task.result or "")[-1500:]}\n\n'
          f'Su log completo está en Actividad.', cooldown=0)


FAILED_LOGINS_BURST = 10          # failed sign-ins in FAILED_LOGINS_MINUTES, from anywhere: someone is guessing
FAILED_LOGINS_MINUTES = 10
# Audit actions that are always worth a message to whoever runs the platform
ALWAYS_ALERT = {
    'token_created': 'Token creado',
    'two_factor_disabled': '2FA desactivado',
    'user_created': 'Usuario creado',
    'db_manager': 'Gestor de bases de datos de Odoo',
    'offsite_restore': 'Restauración desde S3',
}


def security_event(event):
    """After each audit event: alerts for what may be an attack or must not go unnoticed. Never raises."""
    try:
        _security_event(event)
    except Exception:
        logger.exception('Security alert for %s failed', event.action)


def _security_event(event):
    from datetime import timedelta
    from django.utils import timezone
    from ..audit_models import AuditEvent
    who = event.username or 'alguien'
    where = f' desde {event.ip}' if event.ip else ''
    if event.action == 'login_failed':
        since = timezone.now() - timedelta(minutes=FAILED_LOGINS_MINUTES)
        failures = AuditEvent.objects.filter(action='login_failed', created_at__gte=since)
        if failures.count() >= FAILED_LOGINS_BURST:
            addresses = sorted({ip for ip in failures.values_list('ip', flat=True) if ip})
            accounts = sorted({t for t in failures.values_list('target', flat=True) if t})
            alert('login-failures', f'{failures.count()} inicios de sesión fallidos en {FAILED_LOGINS_MINUTES} minutos',
                  f"Cuentas: {', '.join(accounts[:20]) or '—'}\nDirecciones: {', '.join(addresses[:20]) or '—'}\n\n"
                  f'El acceso se bloquea 15 minutos tras varios fallos por cuenta y dirección. Detalle en Auditoría.',
                  cooldown=3600)
    elif event.action == 'login' and event.user_id and event.ip and (event.user.is_superuser or event.user.is_staff):
        # An administrator from an address never seen for them (not on their first sign-in)
        earlier = AuditEvent.objects.filter(action='login', user_id=event.user_id).exclude(pk=event.pk)
        if earlier.exists() and not earlier.filter(ip=event.ip).exists():
            alert(f'new-ip:{event.user_id}:{event.ip}', f'Administrador {who} entra desde una dirección nueva',
                  f'{who} ha iniciado sesión{where}, una dirección que no había usado antes. Si no fue esa persona, '
                  f'cambia su contraseña y revisa la Auditoría.', cooldown=30 * 86400)
    elif event.action in ALWAYS_ALERT:
        detail = f' ({event.target})' if event.target else ''
        alert(f'audit:{event.pk}', f'{ALWAYS_ALERT[event.action]}{detail} por {who}',
              f'{who}{where}: {ALWAYS_ALERT[event.action]}{detail}. {event.details}\n\nDetalle en Auditoría.', cooldown=0)


def check_server_usage():
    """Disk or memory above 90 % (memory: in the last 5 samples of the minute, not a single spike)."""
    import psutil
    from ..metrics_models import MetricSample
    disk = psutil.disk_usage('/').percent
    if disk >= HIGH_USAGE_PERCENT:
        alert('disk-high', f'Disco al {disk:.0f} %',
              f'El disco del servidor está al {disk:.0f} %. Libera espacio: Dashboard → Limpiar, backups antiguos o '
              f'instancias que ya no uses.')
    else:
        clear('disk-high')
    samples = list(MetricSample.objects.order_by('-timestamp').values_list('memory_percent', flat=True)[:5])
    if len(samples) == 5 and min(samples) >= HIGH_USAGE_PERCENT:
        alert('memory-high', f'Memoria al {samples[0]:.0f} %',
              f'La memoria del servidor lleva 5 minutos por encima del {HIGH_USAGE_PERCENT} % ({samples[0]:.0f} % ahora). '
              f'Detén instancias de prueba o baja su límite de memoria.')
    elif samples and samples[0] < HIGH_USAGE_PERCENT:
        clear('memory-high')


def check_certificates():
    """Running instances whose hosts still have no certificate (once a day per instance)."""
    from ..models import Instance
    from .domains import certificate_problem
    for instance in Instance.objects.filter(status=Instance.Status.RUNNING):
        problem = certificate_problem(instance)
        if problem:
            why = {'rate_limit': "el límite semanal de Let's Encrypt", 'failed': 'la comprobación del dominio falló (¿DNS?)',
                   'error': 'un error de Let\'s Encrypt'}.get(problem['kind'], 'todavía no se ha emitido')
            alert(f'certificate:{instance.pk}', f'Sin certificado HTTPS: {instance.name}',
                  f"{', '.join(problem['hosts'])} no tiene certificado: {why}."
                  + (f" Se reintentará después de {problem['retry_after']}." if problem['retry_after'] else ''),
                  cooldown=24 * 3600)


def monthly_usage_report(now=None):
    """On the 1st of every month: the usage of each project, by email to the administrators (or notification addresses)."""
    from django.utils import timezone
    from ..permissions import get_global_config
    from ..project_models import Project
    from ..quotas import project_usage
    from . import mail
    now = now or timezone.now()
    if now.day != 1 or not cache.add(f'usage-report:{now:%Y-%m}', 1, 40 * 86400):
        return False
    config = get_global_config()
    recipients = _recipients(config) if config else []
    if not recipients or mail.smtp_config() is None:
        return False
    lines = []
    for row in project_usage(Project.objects.prefetch_related('instances')):
        quota = f" (cuota {row['max_memory_mb']} MB)" if row['max_memory_mb'] else ''
        disk = '' if row['disk_mb'] is None else f" · disco {row['disk_mb']} MB · backups {row['backups_mb']} MB"
        lines.append(f"- {row['project'].name}: {row['instances']} instancias ({row['running']} en marcha) · "
                     f"RAM reservada {row['memory_mb']} MB{quota}{disk}")
    sent, _ = mail.send(f'[Community SH] Uso por proyecto · {now:%m/%Y}',
                        'Uso de cada proyecto a día de hoy:\n\n' + '\n'.join(lines or ['(sin proyectos)'])
                        + '\n\nEl detalle y el CSV están en Metrics → Uso por proyecto.', recipients)
    return sent
