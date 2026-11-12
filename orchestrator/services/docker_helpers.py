"""Constants and functions shared by DockerService and its parts (re-exported by docker_service)."""
import os
import re
from django.conf import settings

ODOO_DATA_DIR = '/var/lib/odoo'

# Google Chrome in an Odoo container (Debian or Ubuntu): Ubuntu's own chromium is a snap, which Docker cannot run
BROWSER_SCRIPT = r'''set -e
if command -v google-chrome >/dev/null 2>&1; then google-chrome --version; exit 0; fi
arch=$(dpkg --print-architecture)
if [ "$arch" != amd64 ]; then echo "Google Chrome solo existe para amd64 y este servidor es $arch"; exit 3; fi
export DEBIAN_FRONTEND=noninteractive
echo "Descargando Google Chrome..."
url=https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
if command -v curl >/dev/null 2>&1; then curl -fsSL -o /tmp/google-chrome.deb "$url"
else python3 -c "import urllib.request, sys; urllib.request.urlretrieve(sys.argv[1], '/tmp/google-chrome.deb')" "$url"; fi
echo "Instalando Google Chrome y sus dependencias..."
apt-get update -qq
apt-get install -y -qq --no-install-recommends /tmp/google-chrome.deb fonts-liberation
rm -f /tmp/google-chrome.deb
rm -rf /var/lib/apt/lists/*
google-chrome --version
'''

# Instances come back after a reboot of the server, and stay down when stopped from the panel
RESTART_POLICY = {'Name': 'unless-stopped'}

PIP_INSTALL = re.compile(r'^\s*(pip3?|python3?\s+-m\s+pip)\s+install(\s.*)?$', re.S)


def pip_user_command(command):
    """`pip install x` -> `pip install --user --break-system-packages x`: see DockerService.pip_install."""
    match = PIP_INSTALL.match(command)
    if not match:
        return command
    args = match.group(2) or ''
    if any(flag in args.split() for flag in ('--user', '-t', '--target', '--prefix', '--root')):
        return command
    return f'{match.group(1)} install --user --break-system-packages{args}'


def host_path(path):
    """
    Translate a path inside this app's container into the path the Docker daemon sees.
    The project is mounted at BASE_DIR; HOST_WORKDIR is where it lives on the host.
    """
    path = str(path)
    base = str(settings.BASE_DIR)
    host_workdir = os.environ.get('HOST_WORKDIR', '').rstrip('/')
    if host_workdir and (path == base or path.startswith(base + os.sep)):
        return host_workdir + path[len(base):]
    return path


def odoo_major(odoo_version):
    return int(float(odoo_version))


def odoo_config_target(odoo_version):
    # Odoo 8-9 images read OPENERP_SERVER, every later one (10.0 included) ODOO_RC
    if odoo_major(odoo_version) <= 9:
        return '/etc/odoo/openerp-server.conf'
    return '/etc/odoo/odoo.conf'


def odoo_command(odoo_version):
    """The server binary inside the image: Odoo 8-9 still ship it as openerp-server."""
    return 'openerp-server' if odoo_major(odoo_version) <= 9 else 'odoo'


PANEL_ADDONS_DIR = '/mnt/community-sh-addons'
DEMO_MIN_VERSION = 18
# How Odoo containers reach the panel (they share the community-sh_web network)
PANEL_INTERNAL_URL = 'http://app:8000'


def memory_options(instance):
    """docker run options for the memory cap of the Odoo container (no swap beyond it)."""
    if not instance.memory_limit_mb:
        return {}
    limit = f'{instance.memory_limit_mb}m'
    return {'mem_limit': limit, 'memswap_limit': limit}


def admin_login_secret(instance):
    """Key the panel and the instance's community_sh_login module share to sign admin links."""
    import hashlib
    return hashlib.sha256(f'community-sh-login:{instance.master_password}'.encode()).hexdigest()



def published_ip():
    """
    Where Odoo's port is published on the host. With a domain and HTTPS (Traefik) Odoo is reached
    through it, so the port only listens on the host itself: nobody can skip HTTPS or Traefik.
    Without a domain the port is the way in (http://IP:port). ODOO_PUBLISH_IP in .env overrides it.
    """
    from .domains import acme_enabled, main_domain
    configured = os.environ.get('ODOO_PUBLISH_IP', '').strip()
    if configured:
        return configured
    return '127.0.0.1' if main_domain() and acme_enabled() else '0.0.0.0'


def odoo_password_hash(password, rounds=600_000):
    """The pbkdf2-sha512 hash in the passlib format Odoo checks: $pbkdf2-sha512$rounds$salt$checksum (adapted base64)."""
    import base64
    import hashlib
    import secrets

    def ab64(data):
        return base64.b64encode(data).decode().rstrip('=').replace('+', '.')

    salt = secrets.token_bytes(16)
    checksum = hashlib.pbkdf2_hmac('sha512', password.encode(), salt, rounds)
    return f'$pbkdf2-sha512${rounds}${ab64(salt)}${ab64(checksum)}'


def read_backup_metadata(path):
    """
    Describe a backup file. Formats: the panel's ZIP (database.dump + metadata.json), Odoo's own
    database-manager ZIP (dump.sql + filestore/ + manifest.json) and a bare pg_dump custom file.
    Returns {'format', 'database_name', 'odoo_version', 'has_filestore'}.
    """
    import json
    import zipfile
    if not zipfile.is_zipfile(path):
        with open(path, 'rb') as f:
            if f.read(5) != b'PGDMP':
                raise Exception('Formato no reconocido: sube un ZIP del panel, un ZIP de Odoo o un .dump de PostgreSQL')
        return {'format': 'pg_dump', 'database_name': None, 'odoo_version': None, 'has_filestore': False}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        has_filestore = any(n.startswith('filestore/') and not n.endswith('/') for n in names)
        if 'database.dump' in names:
            metadata = json.loads(zf.read('metadata.json')) if 'metadata.json' in names else {}
            return {'format': 'panel', 'database_name': metadata.get('database_name'),
                    'odoo_version': metadata.get('odoo_version'), 'has_filestore': has_filestore}
        if 'dump.sql' in names:
            manifest = json.loads(zf.read('manifest.json')) if 'manifest.json' in names else {}
            version = str(manifest.get('version') or manifest.get('version_info', [''])[0] or '')
            major = version.split('.')[0] if version else ''
            return {'format': 'odoo', 'database_name': manifest.get('db_name'),
                    'odoo_version': f'{major}.0' if major.isdigit() else None, 'has_filestore': has_filestore}
    raise Exception('El ZIP no contiene database.dump (backup del panel) ni dump.sql (backup de Odoo)')


def postgres_image(odoo_version):
    """PostgreSQL release each Odoo version supports (Odoo 20 needs 16+, Odoo 10-11 predate 12)."""
    major = odoo_major(odoo_version)
    if major <= 9:
        return 'postgres:9.6'
    if major <= 11:
        return 'postgres:10'
    if major <= 13:
        return 'postgres:12'
    if major <= 15:
        return 'postgres:13'
    if major <= 17:
        return 'postgres:15'
    return 'postgres:16'


def log_config():
    """Docker logs of every container the panel creates are capped (20 MB x 3 files): a looping error can't fill the disk."""
    import docker
    return docker.types.LogConfig(type='json-file', config={'max-size': '20m', 'max-file': '3'})
