"""
Moving an instance to another server: from the panel's to a node, from a node to the panel's, or between nodes.

Its Odoo stops on the source; every database (pg_dumpall) and the filestore travel through the panel in files (not in
memory); the target gets the same Postgres image, its Odoo is deployed with the workspace the panel keeps, and the
routes of Traefik follow it. The source is only removed once the target has every database; if anything fails before,
the instance goes back to the source as it was. Domains, certificates, backups and the code don't change.
"""
import os
import shutil
import tempfile

import docker
from django.conf import settings

from ..models import Instance
from ..task_log import line, progress
from .docker_helpers import ODOO_DATA_DIR

GB = 1024 ** 3
DUMP = 'move_dump.sql'


def server_label(server):
    return server.name if server is not None else 'este servidor (panel)'


def _to_file(stream, path):
    """A tar stream of the Docker API onto disk, chunk by chunk."""
    with open(path, 'wb') as f:
        for chunk in stream:
            f.write(chunk)
    return os.path.getsize(path)


def _check_space(target, needed):
    """The target needs room for the data and its unpacked copy in /tmp of Postgres while restoring."""
    from . import nodes
    if target is None:
        free = shutil.disk_usage(settings.BASE_DIR).free
    else:
        nodes.refresh_usage(target)
        free = (target.disk_free_gb or 0) * GB
    wanted = 2 * needed + 2 * GB
    if free < wanted:
        raise Exception(f'{server_label(target)} no tiene disco suficiente: {free / GB:.1f} GB libres, '
                        f'hacen falta unos {wanted / GB:.1f} GB')


def check_move(instance, target):
    """Why the instance can't go to `target` (None = the panel's server), or ''."""
    if instance.server_id == (target.pk if target is not None else None):
        return f'{instance.name} ya está en {server_label(target)}'
    if target is not None and not target.ready:
        return f'El servidor {target.name} no está listo: prepáralo en Servidores'
    if not instance.container_id:
        return 'La instancia todavía no se ha desplegado'
    if instance.status == Instance.Status.DEPLOYING:
        return 'La instancia se está desplegando: espera a que termine'
    return ''


def move_instance(instance, target):
    """Move the instance to `target` (a Server, or None for the panel's server). Returns notes for the task log."""
    from . import nodes
    from .docker_service import DockerService
    from ..traefik_service import TraefikService

    problem = check_move(instance, target)
    if problem:
        raise Exception(problem)
    name = instance.name
    origin_server = instance.server
    source = DockerService(instance)
    destination = DockerService(target)
    source_db = source._start_db_container(instance)
    source_odoo = source._get_container(f'odoo_{name}')
    if source_db is None or source_odoo is None:
        raise Exception(f'No se encuentran los contenedores de {name} en {server_label(origin_server)}')
    for container in (f'odoo_{name}', f'db_{name}'):
        if destination._get_container(container) is not None:
            raise Exception(f'Ya existe un contenedor {container} en {server_label(target)}: quítalo antes de mover la instancia')

    was_running = source_odoo.status == 'running'
    before = {'server': origin_server, 'data_volume': instance.data_volume, 'port': instance.port,
              'container_id': instance.container_id, 'status': instance.status}
    db_image = source_db.attrs['Config'].get('Image') or None
    notes = [f'De {server_label(origin_server)} a {server_label(target)}']
    os.makedirs(os.path.join(settings.BASE_DIR, 'backups'), exist_ok=True)
    workdir = tempfile.mkdtemp(prefix=f'.move-{name}-', dir=os.path.join(settings.BASE_DIR, 'backups'))
    switched = False
    try:
        # 1. Out of the source, with Odoo stopped: nothing changes while it travels
        progress(5, f'Deteniendo Odoo en {server_label(origin_server)}')
        Instance.objects.filter(pk=instance.pk).update(status=Instance.Status.DEPLOYING)
        if was_running:
            source_odoo.stop()
        source._wait_for_postgres(source_db)
        databases = source._list_user_databases(source_db)
        progress(10, f"Copiando las bases de datos ({', '.join(databases) or 'ninguna'})")
        dump = source_db.exec_run(f'pg_dumpall -U odoo -f /tmp/{DUMP}', environment={'PGPASSWORD': 'odoo'})
        if dump.exit_code != 0:
            raise Exception(f'No se pudieron copiar las bases de datos: {dump.output.decode(errors="replace")[-300:]}')
        dump_tar = os.path.join(workdir, 'databases.tar')
        size = _to_file(source_db.get_archive(f'/tmp/{DUMP}')[0], dump_tar)
        source_db.exec_run(['rm', '-f', f'/tmp/{DUMP}'])
        progress(25, 'Copiando los adjuntos (filestore)')
        filestore_tar = os.path.join(workdir, 'filestore.tar')
        try:
            size += _to_file(source_odoo.get_archive(f'{ODOO_DATA_DIR}/filestore')[0], filestore_tar)
        except docker.errors.NotFound:
            filestore_tar = None
        line(f'Datos a mover: {size / GB:.2f} GB')
        _check_space(target, size)

        # 2. Into the target: its Postgres (same image) with the data, then its Odoo
        progress(35, f'Base de datos en {server_label(target)}')
        instance.server = target
        instance.data_volume = f'odoo_data_{name}'
        network = f'net_{name}'
        try:
            destination.client.networks.get(network)
        except docker.errors.NotFound:
            destination.client.networks.create(network, driver='bridge')
        target_db = destination._ensure_db_container(instance, network, notes, image=db_image)
        destination._wait_for_postgres(target_db)
        progress(40, 'Restaurando las bases de datos')
        with open(dump_tar, 'rb') as f:
            target_db.put_archive('/tmp', f)
        restore = target_db.exec_run(f'psql -U odoo -d postgres -q -f /tmp/{DUMP}', environment={'PGPASSWORD': 'odoo'})
        # psql reports harmless errors (role "odoo" already exists); 2 = it could not connect: nothing restored
        if restore.exit_code == 2:
            raise Exception(f'No se pudieron restaurar las bases de datos: {restore.output.decode(errors="replace")[-300:]}')
        target_db.exec_run(['rm', '-f', f'/tmp/{DUMP}'])
        missing = set(databases) - set(destination._list_user_databases(target_db))
        if missing:
            raise Exception(f"Faltan bases de datos en {server_label(target)} tras restaurar: {', '.join(sorted(missing))}")

        progress(50, f'Desplegando Odoo en {server_label(target)}')
        destination.deploy_instance(instance)
        notes += destination.deploy_notes
        if filestore_tar:
            progress(85, 'Restaurando los adjuntos (filestore)')
            odoo = destination.client.containers.get(f'odoo_{name}')
            with open(filestore_tar, 'rb') as f:
                if not odoo.put_archive(ODOO_DATA_DIR, f):
                    raise Exception('No se pudieron copiar los adjuntos')
            odoo.exec_run(['chown', '-R', 'odoo:odoo', f'{ODOO_DATA_DIR}/filestore'], user='root')
        if not was_running:
            destination.stop_instance(instance)

        # 3. From here the instance lives on the target: routes, then the source goes away
        progress(92, 'Rutas de Traefik')
        switched = True
        ok, message = TraefikService.generate_instance_config(instance)
        if not ok:
            notes.append(f'Traefik: {message}')
        progress(95, f'Quitando la instancia de {server_label(origin_server)}')
        try:
            source.remove_containers(name, before['data_volume'], container_id=before['container_id'])
            if origin_server is not None:
                nodes.remove_workspace(instance, server=origin_server)
        except Exception as e:
            notes.append(f'Aviso: no se pudo limpiar {server_label(origin_server)} del todo ({e}); la instancia ya funciona en '
                         f'{server_label(target)}. Revisa los contenedores odoo_{name} y db_{name} allí')
        notes.append(f"{name} está ahora en {server_label(target)} con {len(databases)} base(s) de datos"
                     f"{'' if filestore_tar else ' (sin adjuntos)'}")
        return notes
    except Exception:
        if not switched:
            _roll_back(instance, before, destination, source_odoo, was_running)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _roll_back(instance, before, destination, source_odoo, was_running):
    """The move failed before switching: whatever reached the target goes, and the instance runs on the source again."""
    from . import nodes
    from ..traefik_service import TraefikService
    line(f'Deshaciendo: {instance.name} vuelve a {server_label(before["server"])}')
    try:
        destination.remove_containers(instance.name, f'odoo_data_{instance.name}')
        if destination.server is not None:
            nodes.remove_workspace(instance, server=destination.server)
    except Exception as e:
        line(f'No se pudo limpiar {server_label(destination.server)}: {e}')
    for field, value in before.items():
        setattr(instance, field, value)
    if was_running:
        try:
            source_odoo.start()
        except Exception as e:
            line(f'No se pudo volver a arrancar Odoo en el origen: {e}')
            instance.status = Instance.Status.ERROR
    instance.save()
    TraefikService.generate_instance_config(instance)
