"""Docker administration: list and manage containers, images, volumes and networks."""
import docker

# Resources of the panel itself: never stopped or removed from the UI
PROTECTED_PREFIX = 'community-sh'
DEFAULT_NETWORKS = {'bridge', 'host', 'none'}


def _client():
    return docker.from_env()


def _is_protected_container(container):
    return container.labels.get('com.docker.compose.project') == PROTECTED_PREFIX or container.name.startswith(PROTECTED_PREFIX)


def overview():
    from ..container_models import Container as AppContainer
    from ..models import Instance

    client = _client()
    instances_by_container = {f'odoo_{i.name}': i for i in Instance.objects.all()}
    instances_by_container.update({f'db_{i.name}': i for i in Instance.objects.all()})
    app_containers = set(AppContainer.objects.values_list('name', flat=True))
    volume_owners = {i.data_volume: i for i in Instance.objects.exclude(data_volume='')}

    containers = []
    for c in client.containers.list(all=True):
        ports = sorted({b['HostPort'] for bindings in (c.attrs['NetworkSettings'].get('Ports') or {}).values() if bindings for b in bindings})
        containers.append({
            'id': c.short_id, 'name': c.name, 'status': c.status,
            'image': c.attrs['Config'].get('Image', ''), 'ports': ports,
            'created': c.attrs.get('Created', '')[:19].replace('T', ' '),
            'protected': _is_protected_container(c),
            'instance': instances_by_container.get(c.name),
            'managed_container': c.name in app_containers,
        })
    used_images = {c.attrs['Image'] for c in client.containers.list(all=True)}
    images = []
    for img in client.images.list():
        images.append({
            'id': img.short_id.replace('sha256:', ''), 'full_id': img.id,
            'tags': img.tags or ['<none>'], 'size': img.attrs.get('Size', 0),
            'created': img.attrs.get('Created', '')[:19].replace('T', ' '),
            'in_use': img.id in used_images,
        })
    volume_users = {}
    for c in client.containers.list(all=True):
        for mount in c.attrs.get('Mounts', []):
            if mount.get('Type') == 'volume':
                volume_users.setdefault(mount['Name'], []).append(c.name)
    volumes = []
    for v in client.volumes.list():
        volumes.append({
            'name': v.name, 'driver': v.attrs.get('Driver'),
            'created': (v.attrs.get('CreatedAt') or '')[:19].replace('T', ' '),
            'used_by': volume_users.get(v.name, []),
            'instance': volume_owners.get(v.name),
            'protected': v.name.startswith(PROTECTED_PREFIX),
        })
    networks = []
    for n in client.networks.list():
        networks.append({
            'id': n.short_id, 'name': n.name, 'driver': n.attrs.get('Driver'),
            'internal': n.attrs.get('Internal', False),
            'containers': len(n.attrs.get('Containers') or {}),
            'protected': n.name in DEFAULT_NETWORKS or n.name.startswith(PROTECTED_PREFIX),
        })
    df = client.df()
    return {
        'containers': sorted(containers, key=lambda c: (c['status'] != 'running', c['name'])),
        'images': sorted(images, key=lambda i: i['tags'][0]),
        'volumes': sorted(volumes, key=lambda v: (not v['used_by'], v['name'])),
        'networks': sorted(networks, key=lambda n: n['name']),
        'disk': {
            'images': sum(i.get('Size', 0) for i in df.get('Images') or []),
            'containers': sum(c.get('SizeRw', 0) or 0 for c in df.get('Containers') or []),
            'volumes': sum((v.get('UsageData') or {}).get('Size', 0) for v in df.get('Volumes') or [] if (v.get('UsageData') or {}).get('Size', 0) > 0),
            'build_cache': sum(b.get('Size', 0) for b in df.get('BuildCache') or []),
        },
        'version': client.version().get('Version'),
    }


def container_action(container_id, action):
    container = _client().containers.get(container_id)
    if _is_protected_container(container):
        raise PermissionError(f'{container.name} es parte del panel y no se gestiona desde aquí')
    if action == 'start':
        container.start()
    elif action == 'stop':
        container.stop()
    elif action == 'restart':
        container.restart()
    elif action == 'remove':
        container.remove(force=True)
    else:
        raise ValueError(action)
    return container.name


def container_logs(container_id, lines=300):
    container = _client().containers.get(container_id)
    return container.name, container.logs(tail=lines, timestamps=True).decode('utf-8', errors='replace')


def remove_image(image_id):
    _client().images.remove(image_id)


def remove_volume(name):
    if name.startswith(PROTECTED_PREFIX):
        raise PermissionError(f'{name} es parte del panel')
    _client().volumes.get(name).remove()


def remove_network(network_id):
    network = _client().networks.get(network_id)
    if network.name in DEFAULT_NETWORKS or network.name.startswith(PROTECTED_PREFIX):
        raise PermissionError(f'{network.name} no se puede eliminar')
    network.remove()


def prune(kind):
    client = _client()
    if kind == 'containers':
        result = client.containers.prune()
        return len(result.get('ContainersDeleted') or []), result.get('SpaceReclaimed', 0)
    if kind == 'images':
        result = client.images.prune(filters={'dangling': True})
        return len(result.get('ImagesDeleted') or []), result.get('SpaceReclaimed', 0)
    if kind == 'volumes':
        result = client.volumes.prune()
        return len(result.get('VolumesDeleted') or []), result.get('SpaceReclaimed', 0)
    if kind == 'networks':
        result = client.networks.prune()
        return len(result.get('NetworksDeleted') or []), 0
    raise ValueError(kind)


def pull_image(reference):
    repository, _, tag = reference.partition(':')
    image = _client().images.pull(repository, tag=tag or 'latest')
    return image.tags[0] if image.tags else image.short_id
