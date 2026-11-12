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
