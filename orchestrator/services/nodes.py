"""
Remote servers (nodes) that run instances besides the panel's own server.

- Docker: the worker talks to a node's daemon over SSH (docker-py ssh://, its key in the worker's own volume at
  ~/.ssh); the web container, which has no key, through the filtering Docker proxy (scripts/docker_proxy.py)
  the panel starts on the node, listening only on its private IP (NODE_DOCKER=proxy in its environment).
- Files: the panel keeps the workspace of every instance (code, odoo.conf, repositories) and copies it to the
  node with rsync before deploying or restarting it; the node mounts its copy.
- Traffic: Traefik stays on the panel and sends each host to http://<private IP>:<port> of the node.
"""
import logging
import os
import shlex
import subprocess
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

NODE_PROXY_PORT = 2375
NODE_PROXY_NAME = 'community-sh-docker-proxy'
# Compose project label of the node's own containers: the proxy refuses to enter or remove them
NODE_PROJECT = 'community-sh-node'
PROXY_IMAGE = 'python:3.12-slim'
SSH_DIR = os.path.expanduser('~/.ssh')
KEY_PATH = os.path.join(SSH_DIR, 'id_ed25519')
KNOWN_HOSTS = os.path.join(SSH_DIR, 'known_hosts')
PANEL_ADDONS = os.path.join('orchestrator', 'odoo_addons')


class NodeError(Exception):
    pass


def via_proxy():
    """The web container reaches the nodes through their Docker proxy; the workers over SSH."""
    return os.environ.get('NODE_DOCKER', '') == 'proxy'


# One client per node and process: an SSH connection costs a handshake and leaves a thread behind
_clients = {}
_lock = threading.Lock()


def _alive(client):
    adapter = getattr(client.api, '_custom_adapter', None)
    ssh = getattr(adapter, 'ssh_client', None)
    if ssh is None:
        return True  # tcp:// (the proxy): a plain HTTP connection pool
    transport = ssh.get_transport()
    return transport is not None and transport.is_active()


def docker_client(server=None):
    """The Docker daemon of a server: this one (None) or a node."""
    import docker
    if server is None:
        return docker.from_env()
    proxy = via_proxy()
    key = (server.pk, server.host, server.ssh_user, server.ssh_port, proxy)
    with _lock:
        client = _clients.get(key)
        if client is not None and _alive(client):
            return client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        try:
            if proxy:
                client = proxy_client(server, timeout=60)
            else:
                client = docker.DockerClient(base_url=f'ssh://{server.ssh_user}@{server.host}:{server.ssh_port}', timeout=60)
        except Exception as e:
            raise NodeError(f'No se puede conectar con el servidor {server.name} ({server.host}): {e}') from e
        _clients[key] = client
        return client


def proxy_client(server, timeout=60):
    """The node's Docker proxy, with the server's token on every request (APIClient is a requests session)."""
    import docker
    client = docker.DockerClient(base_url=f'tcp://{server.host}:{NODE_PROXY_PORT}', timeout=timeout)
    client.api.headers['X-Proxy-Token'] = server.proxy_token
    return client


def forget_client(server):
    with _lock:
        for key in [k for k in _clients if k[0] == server.pk]:
            try:
                _clients.pop(key).close()
            except Exception:
                pass


def node_path(server, path):
    """A path of the panel's project folder (an instance's workspace, the panel addons) on the node."""
    relative = os.path.relpath(str(path), str(settings.BASE_DIR))
    if relative.startswith('..'):
        raise NodeError(f'{path} no está dentro del panel')
    return server.workdir.rstrip('/') + '/' + relative


def odoo_base_url(instance):
    """Where the panel (Traefik, health checks, Odoo's API) reaches the instance's Odoo; None before its first deploy."""
    if instance.server_id:
        return f'http://{instance.server.host}:{instance.port}' if instance.port else None
    return f'http://odoo_{instance.name}:8069'


def panel_url_for(instance):
    """How the instance's Odoo reaches the panel ("/ia" in a chatter): a node isn't on the panel's Docker network."""
    from .docker_helpers import PANEL_INTERNAL_URL
    if not instance.server_id:
        return PANEL_INTERNAL_URL
    from .domains import acme_enabled, main_domain
    domain = main_domain()
    return f"{'https' if acme_enabled() else 'http'}://{domain}" if domain else PANEL_INTERNAL_URL


# --- SSH (worker only) -------------------------------------------------------------------------------------

def ensure_key():
    """The worker's SSH key (created once in its volume); its public half goes to the database for the Servers page."""
    from ..server_models import PanelKey
    os.makedirs(SSH_DIR, mode=0o700, exist_ok=True)
    if not os.path.exists(KEY_PATH):
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'community-sh-panel', '-f', KEY_PATH],
                       check=True, capture_output=True, timeout=30)
    with open(KEY_PATH + '.pub') as f:
        public = f.read().strip()
    if PanelKey.current() != public:
        PanelKey.objects.all().delete()
        PanelKey.objects.create(public_key=public)
    return public


def _ssh_options(server):
    return ['-p', str(server.ssh_port), '-i', KEY_PATH, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={KNOWN_HOSTS}', '-o', 'ServerAliveInterval=30']


def _target(server):
    return f'{server.ssh_user}@{server.host}'


def run_ssh(server, command, timeout=120):
    """Run a shell command on the node; returns its output or raises NodeError."""
    try:
        result = subprocess.run(['ssh', *_ssh_options(server), _target(server), command],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise NodeError(f'{server.name}: sin respuesta tras {timeout} s')
    if result.returncode != 0:
        raise NodeError(f'{server.name}: {(result.stderr or result.stdout).strip()[-500:] or f"código {result.returncode}"}')
    return result.stdout


def trust_host(server):
    """Record the node's host key the first time (later connections refuse any other key)."""
    os.makedirs(SSH_DIR, mode=0o700, exist_ok=True)
    name = server.host if server.ssh_port == 22 else f'[{server.host}]:{server.ssh_port}'
    known = subprocess.run(['ssh-keygen', '-F', name, '-f', KNOWN_HOSTS], capture_output=True, timeout=10)
    if known.returncode == 0 and known.stdout:
        return False
    scan = subprocess.run(['ssh-keyscan', '-T', '10', '-p', str(server.ssh_port), server.host],
                          capture_output=True, text=True, timeout=30)
    keys = [line for line in scan.stdout.splitlines() if line and not line.startswith('#')]
    if not keys:
        raise NodeError(f'{server.name}: no responde por SSH en {server.host}:{server.ssh_port}')
    with open(KNOWN_HOSTS, 'a') as f:
        f.write('\n'.join(keys) + '\n')
    return True


def rsync(server, source, destination, delete=True):
    """Copy a folder (source/ -> destination/) or a file of the panel to the node."""
    ssh = shlex.join(['ssh', *_ssh_options(server)])
    parent = destination if source.endswith('/') else os.path.dirname(destination)
    args = ['rsync', '-a', '--numeric-ids', '--exclude=.git', '-e', ssh,
            f'--rsync-path=mkdir -p {shlex.quote(parent)} && rsync']
    if delete:
        args.append('--delete')
    try:
        result = subprocess.run(args + [source, f'{_target(server)}:{destination}'], capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        raise NodeError(f'{server.name}: la copia de {source} no terminó en 30 minutos')
    if result.returncode != 0:
        raise NodeError(f'{server.name}: no se pudo copiar {os.path.basename(source.rstrip("/"))}: {result.stderr.strip()[-500:]}')


def sync_workspace(instance):
    """The instance's code, configuration and repositories, and the panel's own Odoo addons, onto its node."""
    server = instance.server
    workspace = os.path.join(settings.BASE_DIR, 'instances', instance.name)
    rsync(server, workspace + '/', node_path(server, workspace))
    panel_addons = os.path.join(settings.BASE_DIR, PANEL_ADDONS)
    rsync(server, panel_addons + '/', node_path(server, panel_addons))


def remove_workspace(instance):
    path = node_path(instance.server, os.path.join(settings.BASE_DIR, 'instances', instance.name))
    run_ssh(instance.server, f'rm -rf {shlex.quote(path)}')


def rename_workspace(instance, old_name):
    base = os.path.join(settings.BASE_DIR, 'instances')
    old = node_path(instance.server, os.path.join(base, old_name))
    new = node_path(instance.server, os.path.join(base, instance.name))
    run_ssh(instance.server, f'if [ -d {shlex.quote(old)} ] && [ ! -e {shlex.quote(new)} ]; then mv {shlex.quote(old)} {shlex.quote(new)}; fi')


# --- Preparing a node ------------------------------------------------------------------------------------

def bootstrap_command(public_key):
    """What to run once on a new node, as root: Docker, rsync and the panel's key."""
    return (
        'command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh; '
        '(command -v rsync >/dev/null || (apt-get update -qq && apt-get install -y -qq rsync)); '
        'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
        f"(grep -qF {shlex.quote(public_key)} ~/.ssh/authorized_keys 2>/dev/null || echo {shlex.quote(public_key)} >> ~/.ssh/authorized_keys)"
    )


def _start_proxy(server, client):
    """The filtering Docker proxy of the node for the panel's web container, on the private IP only."""
    import docker
    from .docker_helpers import RESTART_POLICY, log_config
    try:
        client.images.get(PROXY_IMAGE)
    except docker.errors.ImageNotFound:
        repository, tag = PROXY_IMAGE.rsplit(':', 1)
        client.images.pull(repository, tag=tag)
    try:
        client.containers.get(NODE_PROXY_NAME).remove(force=True)
    except docker.errors.NotFound:
        pass
    workdir = server.workdir.rstrip('/')
    client.containers.run(
        PROXY_IMAGE, ['python', '/opt/proxy/docker_proxy.py'],
        name=NODE_PROXY_NAME, detach=True,
        environment={'HOST_WORKDIR': workdir, 'DOCKER_PROXY_PROJECT': NODE_PROJECT, 'PYTHONUNBUFFERED': '1',
                     'DOCKER_PROXY_TOKEN': server.proxy_token},
        labels={'com.docker.compose.project': NODE_PROJECT},
        volumes={
            f'{workdir}/docker_proxy.py': {'bind': '/opt/proxy/docker_proxy.py', 'mode': 'ro'},
            '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'rw'},
            # At their host path, read-only: the proxy checks for symlinks before letting a folder be mounted
            workdir: {'bind': workdir, 'mode': 'ro'},
        },
        ports={f'{NODE_PROXY_PORT}/tcp': (server.host, NODE_PROXY_PORT)},
        read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
        restart_policy=RESTART_POLICY, log_config=log_config(),
    )


USAGE_EVERY_SECONDS = 300
HIGH_USAGE_PERCENT = 90


def refresh_usage(server):
    """CPUs, memory, load and disk of the node in one SSH call; stored on the server. Raises NodeError."""
    from django.utils import timezone
    output = run_ssh(server, (
        "nproc; awk '/^MemTotal|^MemAvailable/ {print $2}' /proc/meminfo; cut -d' ' -f1 /proc/loadavg; "
        f"df -P -BG {shlex.quote(server.workdir)} | awk 'NR==2 {{print $2, $4}}'"
    ), timeout=30)
    try:
        lines = output.split()
        cpus, mem_total_kb, mem_available_kb, load = int(lines[0]), int(lines[1]), int(lines[2]), float(lines[3])
        disk_total, disk_free = int(lines[4].rstrip('G')), int(lines[5].rstrip('G'))
    except (IndexError, ValueError):
        raise NodeError(f'{server.name}: respuesta inesperada al leer sus recursos: {output[:200]!r}')
    server.cpus, server.load_1m = cpus, load
    server.memory_mb, server.memory_available_mb = mem_total_kb // 1024, mem_available_kb // 1024
    server.disk_total_gb, server.disk_free_gb = disk_total, disk_free
    server.usage_at = timezone.now()
    server.save(update_fields=['cpus', 'load_1m', 'memory_mb', 'memory_available_mb', 'disk_total_gb', 'disk_free_gb', 'usage_at'])


def check_usage(force=False):
    """
    Every few minutes (worker): the usage of every ready node, with an alert when its disk or memory passes 90 %
    or it stops answering over SSH. Returns the names of the nodes that could not be read.
    """
    from django.core.cache import cache
    from ..server_models import Server
    from . import alerts
    if not force and not cache.add('node-usage-run', 1, USAGE_EVERY_SECONDS - 5):
        return []
    failed = []
    for server in Server.objects.filter(status=Server.Status.READY):
        try:
            refresh_usage(server)
        except Exception as e:
            failed.append(server.name)
            alerts.alert(f'node-down:{server.pk}', f'Servidor {server.name} sin respuesta',
                         f'No se pudo leer el servidor {server.name} ({server.host}) por SSH: {e}.\n'
                         'Sus instancias pueden estar caídas: mira Servidores en el panel.')
            continue
        alerts.clear(f'node-down:{server.pk}')
        for kind, percent, label in (('disk', server.disk_percent, 'Disco'), ('memory', server.memory_percent, 'Memoria')):
            key = f'node-{kind}:{server.pk}'
            if percent is not None and percent >= HIGH_USAGE_PERCENT:
                alerts.alert(key, f'{label} de {server.name} al {percent} %',
                             f'{label} del servidor {server.name} ({server.host}) al {percent} %. '
                             'Libera espacio o memoria, o lleva instancias a otro servidor.')
            else:
                alerts.clear(key)
    return failed


def setup_server(server, progress=lambda percent, step: None):
    """
    Check a node and prepare it: its host key, Docker, the work folder, the panel's addons and the Docker proxy.
    Safe to repeat (it also refreshes its CPU, memory and disk). Raises NodeError with what to fix.
    """
    from django.utils import timezone
    from .domains import main_domain
    if not main_domain():
        raise NodeError('Los servidores remotos necesitan el dominio principal configurado (Configuración → Dominio): '
                        'sus instancias se publican por el Traefik del panel')
    progress(5, 'Clave del panel')
    ensure_key()
    progress(10, f'Conectando por SSH con {server.host}')
    trust_host(server)
    try:
        version = run_ssh(server, "docker version --format '{{.Server.Version}}'", timeout=60).strip()
    except NodeError as e:
        raise NodeError(f'{e} (¿está instalado Docker y autorizada la clave del panel? Ejecuta el comando de preparación)')
    workdir = shlex.quote(server.workdir.rstrip('/'))
    run_ssh(server, f'mkdir -p {workdir}/instances {workdir}/orchestrator && command -v rsync >/dev/null '
                    '|| { echo "Falta rsync: apt-get install -y rsync" >&2; exit 1; }')
    progress(35, 'Copiando los módulos del panel y el proxy de Docker')
    panel_addons = os.path.join(settings.BASE_DIR, PANEL_ADDONS)
    rsync(server, panel_addons + '/', node_path(server, panel_addons))
    rsync(server, os.path.join(settings.BASE_DIR, 'scripts', 'docker_proxy.py'),
          f'{server.workdir.rstrip("/")}/docker_proxy.py', delete=False)
    progress(55, 'Docker por SSH')
    forget_client(server)
    client = docker_client(server)
    progress(65, 'Arrancando el proxy de Docker del nodo')
    _start_proxy(server, client)
    progress(85, 'Recursos del servidor')
    refresh_usage(server)
    _check_proxy(server)
    server.docker_version = version[:50]
    server.status = server.Status.READY
    server.last_error = ''
    server.checked_at = timezone.now()
    server.save()


def _check_proxy(server, attempts=10):
    """The web container will use the node's proxy: it has to answer over the private network."""
    import time
    error = None
    for _ in range(attempts):
        try:
            proxy_client(server, timeout=10).ping()
            return
        except Exception as e:
            error = e
            time.sleep(1)
    raise NodeError(f'El proxy de Docker del nodo no responde en {server.host}:{NODE_PROXY_PORT}: {error}')
