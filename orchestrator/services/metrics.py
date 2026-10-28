"""Server, Docker and instance metrics for the Metrics page (rendered and polled as JSON)."""
from concurrent.futures import ThreadPoolExecutor

import docker
import psutil
from django.db.models import Count

GB = 1024 ** 3
MB = 1024 ** 2


def _container_stats(container):
    try:
        stats = container.stats(stream=False)
    except Exception:
        return None
    cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
    system_delta = stats['cpu_stats'].get('system_cpu_usage', 0) - stats['precpu_stats'].get('system_cpu_usage', 0)
    online_cpus = stats['cpu_stats'].get('online_cpus') or len(stats['cpu_stats']['cpu_usage'].get('percpu_usage') or [1])
    cpu = (cpu_delta / system_delta) * online_cpus * 100 if system_delta > 0 and cpu_delta > 0 else 0.0

    memory_usage = stats['memory_stats'].get('usage', 0)
    memory_limit = stats['memory_stats'].get('limit', 0) or 1
    networks = stats.get('networks', {}).values()
    return {
        'name': container.name,
        'cpu_percent': round(cpu, 1),
        'memory_percent': round(memory_usage / memory_limit * 100, 1),
        'memory_usage_mb': round(memory_usage / MB),
        'memory_limit_mb': round(memory_limit / MB),
        'network_rx_mb': round(sum(n.get('rx_bytes', 0) for n in networks) / MB, 1),
        'network_tx_mb': round(sum(n.get('tx_bytes', 0) for n in networks) / MB, 1),
    }


def collect_metrics(include_containers=False):
    from ..models import Instance

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    client = docker.from_env()
    containers = client.containers.list(all=True)
    running = [c for c in containers if c.status == 'running']
    status_counts = dict(Instance.objects.values_list('status').annotate(count=Count('id')))

    data = {
        'cpu_percent': round(psutil.cpu_percent(interval=0.5), 1),
        'cpu_count': psutil.cpu_count(),
        'memory_percent': round(memory.percent, 1),
        'memory_used_gb': round(memory.used / GB, 1),
        'memory_total_gb': round(memory.total / GB, 1),
        'disk_percent': round(disk.percent, 1),
        'disk_used_gb': round(disk.used / GB, 1),
        'disk_total_gb': round(disk.total / GB, 1),
        'containers_running': len(running),
        'containers_total': len(containers),
        'docker_version': client.version()['Version'],
        'docker_images': len(client.images.list()),
        'docker_networks': len(client.networks.list()),
        'docker_volumes': len(client.volumes.list()),
        'instances_running': status_counts.get('running', 0),
        'instances_deploying': status_counts.get('deploying', 0),
        'instances_stopped': status_counts.get('stopped', 0),
        'instances_error': status_counts.get('error', 0),
    }
    if include_containers:
        # Docker takes about a second per container to sample stats: do them in parallel
        with ThreadPoolExecutor(max_workers=8) as pool:
            stats = [s for s in pool.map(_container_stats, running) if s]
        data['containers'] = sorted(stats, key=lambda s: s['name'])
    return data
