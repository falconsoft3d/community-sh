"""Indicators of one instance for the Indicators tab: database and filestore sizes, Odoo figures, containers, code
and backups. Read-only: psql SELECTs in the PostgreSQL container, du/find in the Odoo container."""
import os
import subprocess
from datetime import datetime, timezone

from django.conf import settings
from django.core.cache import cache

from .metrics import _container_stats

CACHE_SECONDS = 300

# Odoo figures per database: label key → SQL returning one value (a failing one, e.g. a table of another
# version or a module not installed, is just left out)
ODOO_QUERIES = {
    'odoo_version': "SELECT latest_version FROM ir_module_module WHERE name = 'base'",
    'modules_installed': "SELECT count(*) FROM ir_module_module WHERE state = 'installed'",
    'users_internal': "SELECT count(*) FROM res_users WHERE active AND NOT share",
    'users_portal': "SELECT count(*) FROM res_users WHERE active AND share",
    'companies': "SELECT count(*) FROM res_company",
    'partners': "SELECT count(*) FROM res_partner",
    'attachments': "SELECT count(*) FROM ir_attachment",
    'attachments_in_db_bytes': "SELECT coalesce(sum(octet_length(db_datas)), 0) FROM ir_attachment "
                               "WHERE db_datas IS NOT NULL",
    'messages': "SELECT count(*) FROM mail_message",
    'mail_outgoing': "SELECT count(*) FROM mail_mail WHERE state = 'outgoing'",
    'mail_exception': "SELECT count(*) FROM mail_mail WHERE state = 'exception'",
    'crons_active': "SELECT count(*) FROM ir_cron WHERE active",
    'invoices': "SELECT count(*) FROM account_move WHERE move_type IN ('out_invoice', 'in_invoice', 'out_refund', "
                "'in_refund')",
    'last_login': "SELECT to_char(max(create_date), 'YYYY-MM-DD\"T\"HH24:MI:SS') FROM res_users_log",
    'neutralized': "SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized'",
}
TOP_TABLES_SQL = """
    SELECT c.relname || '|' || pg_total_relation_size(c.oid) || '|' || coalesce(s.n_live_tup, 0)
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
     WHERE c.relkind = 'r' AND n.nspname = 'public'
     ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10"""


def _psql(db_container, database, sql):
    result = db_container.exec_run(['psql', '-U', 'odoo', '-d', database, '-qAtc', sql],
                                   environment={'PGPASSWORD': 'odoo'})
    if result.exit_code != 0:
        return None
    return result.output.decode(errors='replace').strip()


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value or None


def _exec(container, command):
    result = container.exec_run(['sh', '-c', command])
    return result.output.decode(errors='replace').strip() if result.exit_code == 0 else None


def _du_bytes(path, timeout=60):
    """Size of a directory of the panel host (code workspace), or None."""
    if not os.path.isdir(path):
        return None
    try:
        out = subprocess.run(['du', '-sb', path], capture_output=True, text=True, timeout=timeout, check=False)
        return int(out.stdout.split()[0]) if out.returncode == 0 and out.stdout else None
    except (subprocess.TimeoutExpired, ValueError, IndexError, OSError):
        return None


def _container_info(container):
    if container is None:
        return None
    state = container.attrs.get('State', {})
    info = {
        'name': container.name,
        'status': container.status,
        'image': (container.attrs.get('Config') or {}).get('Image'),
        'started_at': state.get('StartedAt') if container.status == 'running' else None,
    }
    if container.status == 'running':
        stats = _container_stats(container) or {}
        info.update({k: stats.get(k) for k in ('cpu_percent', 'memory_usage_mb', 'memory_limit_mb', 'memory_percent')})
    return info


def collect_instance_stats(instance, refresh=False):
    """Indicators of an instance (cached CACHE_SECONDS; refresh=True recomputes)."""
    key = f'instance-stats-{instance.pk}'
    if not refresh:
        cached = cache.get(key)
        if cached:
            return cached
    from .docker_service import DockerService
    service = DockerService(instance)
    odoo = service._get_container(f'odoo_{instance.name}')
    db = service._get_container(f'db_{instance.name}')
    data = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'containers': [c for c in (_container_info(odoo), _container_info(db)) if c],
        'databases': [],
        'warnings': [],
    }
    # databases: size, PostgreSQL figures, Odoo figures, biggest tables
    if db is None or db.status != 'running':
        data['warnings'].append('db_stopped')
    else:
        data['postgres_version'] = _psql(db, 'postgres', 'SHOW server_version')
        data['connections'] = _number(_psql(db, 'postgres', 'SELECT count(*) FROM pg_stat_activity'))
        try:
            databases = service._list_user_databases(db)
        except Exception:
            databases = []
        for name in databases:
            entry = {'name': name, 'size_bytes': _number(_psql(db, 'postgres', f"SELECT pg_database_size('{name}')"))}
            hit = _psql(db, 'postgres', f"SELECT round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 1) "
                                        f"FROM pg_stat_database WHERE datname = '{name}'")
            entry['cache_hit_percent'] = float(hit) if hit not in (None, '') else None
            entry['tables'] = _number(_psql(db, name, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"))
            odoo_values = {}
            for label, sql in ODOO_QUERIES.items():
                value = _psql(db, name, sql)
                if value not in (None, ''):
                    odoo_values[label] = _number(value) if label not in ('odoo_version', 'last_login', 'neutralized') else value
            entry['odoo'] = odoo_values
            top = _psql(db, name, TOP_TABLES_SQL) or ''
            entry['top_tables'] = [
                {'name': parts[0], 'size_bytes': _number(parts[1]), 'rows': _number(parts[2])}
                for parts in (line.split('|') for line in top.splitlines()) if len(parts) == 3
            ]
            data['databases'].append(entry)
    # filestore (attachments) per database and the whole data volume, from the Odoo container
    if odoo is None or odoo.status != 'running':
        data['warnings'].append('odoo_stopped')
    else:
        data_dir = '/var/lib/odoo'
        for entry in data['databases']:
            path = f"{data_dir}/filestore/{entry['name']}"
            size = _exec(odoo, f'du -sb "{path}" 2>/dev/null | cut -f1')
            files = _exec(odoo, f'find "{path}" -type f 2>/dev/null | wc -l')
            entry['filestore_bytes'] = _number(size) if size else 0
            entry['filestore_files'] = _number(files) if files else 0
        volume = _exec(odoo, f'du -sb {data_dir} 2>/dev/null | cut -f1')
        data['data_volume_bytes'] = _number(volume) if volume else None
    # code (addons + extra repositories) and backups kept by the panel
    data['code_bytes'] = _du_bytes(os.path.join(settings.BASE_DIR, 'instances', instance.name))
    backups = list(instance.backups.all())
    sizes = [os.path.getsize(b.file_path) for b in backups if b.file_path and os.path.exists(b.file_path)]
    data['backups'] = {'count': len(backups), 'local_bytes': sum(sizes)}
    data['total_bytes'] = sum(
        (e.get('size_bytes') or 0) + (e.get('filestore_bytes') or 0) for e in data['databases'])
    cache.set(key, data, CACHE_SECONDS)
    return data
