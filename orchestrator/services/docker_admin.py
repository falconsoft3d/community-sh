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
        'cleanup_plan': cleanup_plan(client, df),
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


# What "Limpiar lo no utilizado" can remove, in the order it runs
CLEANUP_KINDS = {
    'containers': 'Contenedores detenidos',
    'images': 'Imágenes sin etiqueta',
    'unused_images': 'Imágenes sin usar',
    'build_cache': 'Caché de build',
    'networks': 'Redes sin uso',
    'volumes': 'Volúmenes sin uso',
}
STOPPED = {'exited', 'created', 'dead'}


def _owned():
    """
    Names the panel still needs although Docker sees them stopped or unused: a stopped instance keeps its
    containers (its Postgres data lives in the anonymous volume of db_<name>), its network and its filestore.
    """
    from ..container_models import Container as AppContainer
    from ..models import Instance

    containers, volumes, networks = set(), set(), set()
    for name, data_volume in Instance.objects.values_list('name', 'data_volume'):
        containers |= {f'odoo_{name}', f'db_{name}'}
        volumes |= {data_volume, f'odoo_data_{name}'} - {''}
        networks.add(f'net_{name}')
    apps = set(AppContainer.objects.values_list('name', flat=True))
    return containers | apps, volumes, networks, tuple(f'{app}_' for app in apps)


def cleanup_plan(client=None, df=None, remove_stopped=True):
    """
    What nothing uses, by kind: {kind: [(name, bytes, docker object)]}. Sizes are an upper bound (images share
    layers). With remove_stopped, what only the removable stopped containers use counts as unused too.
    """
    client = client or _client()
    df = df if df is not None else client.df()
    owned_containers, owned_volumes, owned_networks, app_volume_prefixes = _owned()

    container_sizes = {c['Id']: c.get('SizeRw') or 0 for c in df.get('Containers') or []}
    all_containers = client.containers.list(all=True)
    stopped = [c for c in all_containers
               if c.status in STOPPED and not _is_protected_container(c) and c.name not in owned_containers]
    removed = {c.id for c in stopped} if remove_stopped else set()
    kept = [c for c in all_containers if c.id not in removed]

    used_images, used_networks, used_volumes = set(), set(), set()
    for c in kept:
        used_images.add(c.attrs['Image'])
        used_networks |= set((c.attrs.get('NetworkSettings') or {}).get('Networks') or {})
        used_networks.add(c.attrs.get('HostConfig', {}).get('NetworkMode', ''))
        used_volumes |= {m['Name'] for m in c.attrs.get('Mounts', []) if m.get('Type') == 'volume'}
    images = [img for img in client.images.list() if img.id not in used_images]
    volume_sizes = {v['Name']: max((v.get('UsageData') or {}).get('Size', 0), 0) for v in df.get('Volumes') or []}

    return {
        'containers': [(c.name, container_sizes.get(c.id, 0), c) for c in stopped],
        'images': [(img.short_id.replace('sha256:', ''), img.attrs.get('Size', 0), img) for img in images if not img.tags],
        'unused_images': [(img.tags[0], img.attrs.get('Size', 0), img) for img in images if img.tags],
        'build_cache': [(b.get('ID', ''), b.get('Size', 0), None) for b in df.get('BuildCache') or [] if not b.get('InUse')],
        'networks': [(n.name, 0, n) for n in client.networks.list()
                     if n.name not in used_networks | owned_networks | DEFAULT_NETWORKS
                     and not n.name.startswith(PROTECTED_PREFIX) and not n.attrs.get('Containers')],
        'volumes': [(v.name, volume_sizes.get(v.name, 0), v) for v in client.volumes.list()
                    if v.name not in used_volumes | owned_volumes
                    and not v.name.startswith((PROTECTED_PREFIX,) + app_volume_prefixes)],
    }


def cleanup_summary(plan):
    """The plan for the template: label, count, size and the first names of each kind."""
    return [{'kind': kind, 'label': label, 'count': len(plan[kind]), 'size': sum(size for _, size, _ in plan[kind]),
             'items': [name for name, _, _ in plan[kind][:20]]} for kind, label in CLEANUP_KINDS.items()]


def _remove_image(client, img):
    # An image with several tags goes away when its last tag is removed
    for tag in img.tags or [img.id]:
        client.images.remove(tag)


def cleanup(kinds, progress=None):
    """Remove what nothing uses, of these kinds. Returns {kind: (count, bytes reclaimed)}."""
    client = _client()
    kinds = [kind for kind in CLEANUP_KINDS if kind in kinds]
    plan = cleanup_plan(client, remove_stopped='containers' in kinds)
    results = {}
    for step, kind in enumerate(kinds):
        if progress:
            progress(10 + 85 * step // len(kinds), f'{CLEANUP_KINDS[kind]}: {len(plan[kind])}')
        if kind == 'images':
            result = client.images.prune(filters={'dangling': True})
            results[kind] = len(result.get('ImagesDeleted') or []), result.get('SpaceReclaimed') or 0
            continue
        if kind == 'build_cache':
            result = client.api.prune_builds(all=True)
            results[kind] = len(result.get('CachesDeleted') or []), result.get('SpaceReclaimed') or 0
            continue
        # One by one: what Docker refuses (in use again, a parent image...) is kept and reported
        count, freed = 0, 0
        for name, size, obj in plan[kind]:
            try:
                _remove_image(client, obj) if kind == 'unused_images' else obj.remove()
                print(f'  Eliminado {name}')
                count, freed = count + 1, freed + size
            except docker.errors.APIError as e:
                print(f'  Se conserva {name}: {getattr(e, "explanation", None) or e}')
        results[kind] = count, freed
    return results


def prune(kind):
    """One kind of cleanup, from the buttons of each tab: the same rules as cleaning everything."""
    if kind not in CLEANUP_KINDS:
        raise ValueError(kind)
    return cleanup([kind])[kind]


def pull_image(reference):
    repository, _, tag = reference.partition(':')
    image = _client().images.pull(repository, tag=tag or 'latest')
    return image.tags[0] if image.tags else image.short_id
