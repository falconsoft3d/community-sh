"""
Backups off the server: every backup is also copied to an S3-compatible bucket (AWS S3, Backblaze B2, Cloudflare R2,
Wasabi, MinIO...), so losing the server's disk doesn't lose them. Configured in Settings → Respaldos. Objects older
than the retention are deleted from the bucket after each upload.
"""
import os
from datetime import timedelta

from django.utils import timezone


def offsite_config(config=None):
    """The platform config when the copy off the server is switched on and complete, else None."""
    from ..permissions import get_global_config
    config = config or get_global_config()
    if not config or not config.offsite_enabled or not config.s3_bucket or not config.s3_access_key or not config.s3_secret_key:
        return None
    return config


def client(config):
    import boto3
    from botocore.config import Config
    return boto3.client(
        's3', endpoint_url=config.s3_endpoint_url or None, region_name=config.s3_region or None,
        aws_access_key_id=config.s3_access_key, aws_secret_access_key=config.s3_secret_key,
        config=Config(connect_timeout=15, read_timeout=120, retries={'max_attempts': 3}),
    )


def prefix(config):
    value = (config.s3_prefix or '').strip('/')
    return f'{value}/' if value else ''


def object_key(config, backup):
    return f'{prefix(config)}{backup.instance.name}/{backup.filename}'


def test_connection(config):
    """Write, read back and delete a small object. Returns (ok, message)."""
    try:
        s3 = client(config)
        key = f'{prefix(config)}.community-sh-test'
        s3.put_object(Bucket=config.s3_bucket, Key=key, Body=b'ok')
        s3.head_object(Bucket=config.s3_bucket, Key=key)
        s3.delete_object(Bucket=config.s3_bucket, Key=key)
        return True, f'Conexión correcta: se puede escribir en {config.s3_bucket}/{prefix(config)}'
    except Exception as e:
        return False, f'No se pudo escribir en el bucket: {e}'


def upload(backups, progress=None):
    """Copy these backups (skipping missing files) and apply the retention. Returns notes for the log."""
    config = offsite_config()
    if config is None:
        return ['La copia fuera del servidor no está configurada']
    s3 = client(config)
    notes = []
    for index, backup in enumerate(backups):
        if not os.path.exists(backup.file_path):
            notes.append(f'{backup.filename}: el archivo ya no está en el servidor')
            continue
        if progress:
            progress(10 + 80 * index // max(len(backups), 1), f'Subiendo {backup.filename} ({backup.formatted_size})')
        key = object_key(config, backup)
        s3.upload_file(backup.file_path, config.s3_bucket, key)  # multipart for big files
        backup.offsite_key, backup.offsite_at = key, timezone.now()
        backup.save(update_fields=['offsite_key', 'offsite_at'])
        notes.append(f'{backup.filename} → s3://{config.s3_bucket}/{key}')
    notes += apply_retention(config, s3)
    return notes


def apply_retention(config, s3=None):
    """Delete the objects of the prefix older than the retention days."""
    if not config.offsite_retention_days:
        return []
    s3 = s3 or client(config)
    limit = timezone.now() - timedelta(days=config.offsite_retention_days)
    old = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=config.s3_bucket, Prefix=prefix(config)):
        old += [item['Key'] for item in page.get('Contents', []) if item['LastModified'] < limit]
    for start in range(0, len(old), 1000):
        s3.delete_objects(Bucket=config.s3_bucket, Delete={'Objects': [{'Key': key} for key in old[start:start + 1000]]})
    return [f'Retención: {len(old)} copias de más de {config.offsite_retention_days} días eliminadas del bucket'] if old else []


def queue_upload(backups, user=None):
    """After a backup: its copy off the server, as its own task (a big upload doesn't hold the backup)."""
    from ..task_models import Task
    from ..tasks import enqueue
    backups = [b for b in backups if b is not None]
    if not backups or offsite_config() is None:
        return None
    return enqueue(Task.Kind.OFFSITE_UPLOAD, backups[0].instance, user, backups=[b.pk for b in backups])


PANEL_PREFIX = '_panel/'
PANEL_LOCAL_DAYS = 15


def _panel_db_container():
    import docker
    containers = docker.from_env().containers.list(filters={'label': 'com.docker.compose.service=db'})
    project = os.environ.get('COMPOSE_PROJECT_NAME', '')
    for container in containers:
        if not project or container.labels.get('com.docker.compose.project') == project:
            return container
    return None


def dump_panel_database(target_dir):
    """
    A copy of the panel's own database in target_dir: pg_dump inside its container (the panel's image has no
    pg_dump), gzipped; a copy of the file for SQLite installs. Returns the path.
    """
    import gzip
    import shutil
    from django.conf import settings
    database = settings.DATABASES['default']
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    os.makedirs(target_dir, exist_ok=True)
    if 'sqlite' in database['ENGINE']:
        path = os.path.join(target_dir, f'panel-daily-{stamp}.sqlite3')
        shutil.copy2(database['NAME'], path)
        return path
    container = _panel_db_container()
    if container is None:
        raise Exception('No encuentro el contenedor de la base de datos del panel')
    path = os.path.join(target_dir, f'panel-daily-{stamp}.sql.gz')
    result = container.exec_run(['pg_dump', '-U', database['USER'], '--no-owner', database['NAME']], stream=True, demux=True)
    errors = b''
    with gzip.open(path, 'wb') as out:
        for stdout, stderr in result.output:
            if stdout:
                out.write(stdout)
            if stderr:
                errors += stderr
    with gzip.open(path, 'rb') as check:
        if len(check.read(200)) < 100:
            os.remove(path)
            raise Exception(f'pg_dump no devolvió nada: {errors.decode(errors="replace")[-300:]}')
    os.chmod(path, 0o600)
    return path


def backup_panel(progress=None):
    """Daily: the panel's database (and Traefik's certificate store) to the bucket. Returns notes for the log."""
    from django.conf import settings
    config = offsite_config()
    if config is None:
        return ['La copia fuera del servidor no está configurada']
    target_dir = os.path.join(settings.BASE_DIR, 'backups', 'panel-db')
    if progress:
        progress(10, 'Copiando la base de datos del panel')
    path = dump_panel_database(target_dir)
    s3 = client(config)
    key = f'{prefix(config)}{PANEL_PREFIX}{os.path.basename(path)}'
    if progress:
        progress(60, 'Subiendo la copia al bucket')
    s3.upload_file(path, config.s3_bucket, key)
    notes = [f'Base de datos del panel → s3://{config.s3_bucket}/{key} ({os.path.getsize(path) // 1024} KB)']
    acme = os.path.join(settings.BASE_DIR, 'letsencrypt', 'acme.json')
    if os.path.exists(acme) and os.path.getsize(acme):
        s3.upload_file(acme, config.s3_bucket, f'{prefix(config)}{PANEL_PREFIX}acme.json')
        notes.append('Certificados (acme.json) subidos')
    # The local daily copies are kept a couple of weeks (the bucket keeps them per its retention)
    limit = timezone.now().timestamp() - PANEL_LOCAL_DAYS * 86400
    for name in os.listdir(target_dir):
        old = os.path.join(target_dir, name)
        if name.startswith('panel-daily-') and os.path.getmtime(old) < limit:
            os.remove(old)
    return notes + apply_retention(config, s3)


def queue_daily_panel_backup():
    """Called by the worker every minute: once a day, if the copy off the server is configured."""
    from django.core.cache import cache
    from ..task_models import Task
    from ..tasks import enqueue
    if offsite_config() is None or not cache.add('panel-backup-day', 1, 23 * 3600):
        return None
    return enqueue(Task.Kind.PANEL_BACKUP)


def instance_copies(instance):
    """The copies of this instance in the bucket, newest first: [{'key', 'name', 'size', 'modified'}]."""
    config = offsite_config()
    if config is None:
        return []
    s3 = client(config)
    folder = f'{prefix(config)}{instance.name}/'
    items = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=config.s3_bucket, Prefix=folder):
        items += [{'key': o['Key'], 'name': o['Key'][len(folder):], 'size': o['Size'], 'modified': o['LastModified'].isoformat()}
                  for o in page.get('Contents', []) if not o['Key'].endswith('/')]
    return sorted(items, key=lambda item: item['modified'], reverse=True)


def restore_from_bucket(instance, key, progress=None):
    """Download a copy of this instance from the bucket and restore it over the instance. Returns notes."""
    import tempfile
    from django.conf import settings
    from .docker_service import DockerService
    config = offsite_config()
    if config is None:
        raise Exception('La copia fuera del servidor no está configurada')
    if not key.startswith(f'{prefix(config)}{instance.name}/'):
        raise Exception('Esa copia no es de esta instancia')
    folder = os.path.join(settings.BASE_DIR, 'backups', 'tmp')
    os.makedirs(folder, exist_ok=True)
    path = tempfile.NamedTemporaryFile(dir=folder, suffix='.zip', delete=False).name
    try:
        if progress:
            progress(10, f'Descargando {os.path.basename(key)} del bucket')
        client(config).download_file(config.s3_bucket, key, path)
        if progress:
            progress(40, 'Restaurando')
        DockerService().restore_instance(instance, path)
    finally:
        if os.path.exists(path):
            os.remove(path)
    return [f'Restaurado desde s3://{config.s3_bucket}/{key}']


def check_backup(backup, s3=None, config=None):
    """Problems of one backup file (empty list: it looks restorable)."""
    import zipfile
    from .docker_helpers import read_backup_metadata
    if not os.path.exists(backup.file_path):
        return ['el archivo ya no está en el servidor']
    problems = []
    try:
        info = read_backup_metadata(backup.file_path)
    except Exception as e:
        return [f'no se reconoce: {e}']
    if zipfile.is_zipfile(backup.file_path):
        with zipfile.ZipFile(backup.file_path) as zf:
            broken = zf.testzip()
            if broken:
                problems.append(f'archivo dañado dentro del ZIP: {broken}')
            dump = 'database.dump' if info['format'] == 'panel' else 'dump.sql'
            with zf.open(dump) as f:
                head = f.read(5)
            if info['format'] == 'panel' and head != b'PGDMP':
                problems.append('database.dump no es un volcado de PostgreSQL')
            if zf.getinfo(dump).file_size < 1024:
                problems.append(f'{dump} casi vacío ({zf.getinfo(dump).file_size} bytes)')
    if backup.offsite_key and s3 is not None:
        try:
            size = s3.head_object(Bucket=config.s3_bucket, Key=backup.offsite_key)['ContentLength']
            if size != os.path.getsize(backup.file_path):
                problems.append(f'la copia en S3 mide {size} bytes y la local {os.path.getsize(backup.file_path)}')
        except Exception as e:
            problems.append(f'la copia en S3 no se encuentra: {e}')
    return problems


def verify_backups(progress=None):
    """The latest backup of every instance: intact ZIP, a real database dump and (with S3) the same size there."""
    from ..backup_models import Backup
    from ..models import Instance
    from . import alerts
    config = offsite_config()
    s3 = client(config) if config else None
    notes, failures = [], []
    instances = list(Instance.objects.all())
    for index, instance in enumerate(instances):
        backup = Backup.objects.filter(instance=instance).order_by('-created_at').first()
        if backup is None:
            continue
        if progress:
            progress(5 + 90 * index // max(len(instances), 1), f'Comprobando {backup.filename}')
        problems = check_backup(backup, s3, config)
        if problems:
            failures.append(f'{instance.name} · {backup.filename}: ' + '; '.join(problems))
        else:
            notes.append(f'✓ {instance.name} · {backup.filename}')
    if failures:
        alerts.alert('backups-verify', f'{len(failures)} backups con problemas',
                     'La comprobación de los backups ha encontrado problemas:\n\n' + '\n'.join(failures), cooldown=0)
        raise Exception('Backups con problemas:\n' + '\n'.join(failures) + ('\n\nCorrectos:\n' + '\n'.join(notes) if notes else ''))
    return notes or ['No hay backups que comprobar']


def queue_weekly_verification():
    """Called by the worker every minute: once a week."""
    from django.core.cache import cache
    from ..task_models import Task
    from ..tasks import enqueue
    if not cache.add('backups-verify-week', 1, 7 * 24 * 3600):
        return None
    return enqueue(Task.Kind.BACKUP_VERIFY)
