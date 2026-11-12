"""
Health check of the instances: every few minutes the worker asks each running Odoo for its login page over the
Docker network it shares with them. Two failures in a row mark it as not answering (and alert); the first answer
after that marks it up again (and alerts that it's back). Instances with a task queued or running (a deploy, a
restore...) are skipped: they may be restarting on purpose.
"""
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache
from django.utils import timezone

CHECK_EVERY_SECONDS = 300
TIMEOUT_SECONDS = 10
FAILURES_TO_ALERT = 2


def probe(instance):
    """(answers, milliseconds, error). Any HTTP answer below 500 means Odoo is serving requests."""
    url = f'http://odoo_{instance.name}:8069/web/login'
    started = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Community-SH-health'}),
                                    timeout=TIMEOUT_SECONDS) as response:
            code = response.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return False, None, str(getattr(e, 'reason', None) or e)[:255]
    ms = int((time.monotonic() - started) * 1000)
    return (code < 500), ms, ('' if code < 500 else f'HTTP {code}')


def check_instances(force=False):
    """Check every running instance (at most once every CHECK_EVERY_SECONDS). Returns [(name, 'down'|'up')] changes."""
    from ..models import Instance
    from ..task_models import Task
    from . import alerts
    if not force and not cache.add('health-check-run', 1, CHECK_EVERY_SECONDS - 5):
        return []
    instances = list(Instance.objects.filter(status=Instance.Status.RUNNING))
    busy = set(Task.objects.filter(status__in=(Task.Status.PENDING, Task.Status.RUNNING))
               .exclude(instance=None).values_list('instance_id', flat=True))
    instances = [i for i in instances if i.pk not in busy]
    if not instances:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(instances))) as pool:
        results = list(pool.map(probe, instances))
    now = timezone.now()
    changes = []
    for instance, (ok, ms, error) in zip(instances, results):
        failures = 0 if ok else instance.health_failures + 1
        health = instance.health
        if ok:
            if health == Instance.Health.DOWN:
                changes.append((instance.name, 'up'))
                alerts.clear(f'down:{instance.pk}')
                alerts.alert(f'up:{instance.pk}', f'{instance.name} vuelve a responder',
                             f'{instance.name} ({instance.url}) responde otra vez ({ms} ms).', cooldown=0)
            health = Instance.Health.UP
        elif failures >= FAILURES_TO_ALERT:
            if health != Instance.Health.DOWN:
                changes.append((instance.name, 'down'))
                alerts.alert(f'down:{instance.pk}', f'{instance.name} no responde',
                             f'{instance.name} ({instance.url}) no responde desde hace {failures} comprobaciones: {error}.\n'
                             f'Mira sus logs en el panel o reiníciala.')
            health = Instance.Health.DOWN
        Instance.objects.filter(pk=instance.pk).update(health=health, health_ms=ms, health_checked_at=now,
                                                       health_failures=failures, health_error=error)
    return changes
