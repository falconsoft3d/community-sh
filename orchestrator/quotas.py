"""
Quotas of a project (set by an administrator): how many instances it can have and how much RAM their memory
limits can add up to. Checked wherever an instance is created or grows: form, API, duplicate, move, from a
backup, demos and the memory limit. 0 means no limit.
"""
DEFAULT_MEMORY_MB = 1536


def _memory(instance):
    return instance.memory_limit_mb or DEFAULT_MEMORY_MB


def quota_problem(project, add_instances=1, add_memory_mb=DEFAULT_MEMORY_MB, exclude=None):
    """Why the project can't take this (a message), or None. exclude: an instance being changed, not added."""
    if project is None or (not project.max_instances and not project.max_memory_mb):
        return None
    instances = list(project.instances.exclude(pk=getattr(exclude, 'pk', None)))
    if project.max_instances and len(instances) + add_instances > project.max_instances:
        return (f'El proyecto «{project.name}» ya tiene {len(instances)} de las {project.max_instances} instancias '
                f'que permite su cuota: pide a un administrador que la amplíe')
    if project.max_memory_mb:
        used = sum(_memory(i) for i in instances)
        if used + add_memory_mb > project.max_memory_mb:
            return (f'El proyecto «{project.name}» reserva {used} MB de RAM y su cuota es {project.max_memory_mb} MB: '
                    f'no caben {add_memory_mb} MB más (baja el límite de memoria de alguna instancia o pide que se amplíe)')
    return None


def project_usage(projects):
    """Per project: instances (running), reserved RAM, quota and disk (from the last disk measure, if any)."""
    from django.core.cache import cache
    disk = {row['name']: row for row in (cache.get('instance-disk-usage') or {}).get('rows', [])}
    rows = []
    for project in projects:
        instances = list(project.instances.all())
        disk_rows = [disk[i.name] for i in instances if i.name in disk]
        rows.append({
            'project': project, 'instances': len(instances),
            'running': sum(1 for i in instances if i.status == 'running'),
            'memory_mb': sum(_memory(i) for i in instances),
            'max_instances': project.max_instances, 'max_memory_mb': project.max_memory_mb,
            'disk_mb': sum(r['disk_mb'] for r in disk_rows) if disk_rows else None,
            'backups_mb': sum(r['backups_mb'] for r in disk_rows) if disk_rows else None,
        })
    return sorted(rows, key=lambda r: -r['memory_mb'])
