"""
Background tasks: views enqueue them and the worker (manage.py run_worker) runs them,
so deploys, backups and restores no longer block an HTTP request for minutes.
"""
import logging
import os

from django.db import transaction
from django.utils import timezone

from .backup_models import Backup
from .config_models import GitHubConfig
from .email_notifications import send_instance_notification
from . import task_log
from .models import Instance
from .services import DockerService
from .services.github import create_branch
from .task_models import Task
from .traefik_service import TraefikService

logger = logging.getLogger(__name__)

HANDLERS = {}


def handler(kind):
    def register(func):
        HANDLERS[kind] = func
        return func
    return register


def enqueue(kind, instance=None, user=None, **params):
    if kind == Task.Kind.DEPLOY and instance is not None:
        # Show the instance as deploying while the task waits in the queue
        instance.status = Instance.Status.DEPLOYING
        instance.save(update_fields=['status'])
    return Task.objects.create(kind=kind, instance=instance, created_by=user, params=params)


def _for_queue(queryset, only=(), exclude=()):
    """Tasks of one worker's queue: only these kinds, or every kind but these."""
    if only:
        queryset = queryset.filter(kind__in=only)
    if exclude:
        queryset = queryset.exclude(kind__in=exclude)
    return queryset


def claim_next_task(only=(), exclude=()):
    with transaction.atomic():
        task = (
            _for_queue(Task.objects.select_for_update(skip_locked=True), only, exclude)
            .filter(status=Task.Status.PENDING)
            .order_by('created_at')
            .first()
        )
        if task is None:
            return None
        task.status = Task.Status.RUNNING
        task.started_at = timezone.now()
        task.save(update_fields=['status', 'started_at'])
    return task


def recover_interrupted_tasks(only=(), exclude=()):
    """Tasks left running by a stopped worker (of this queue) will never finish: mark them failed."""
    return _for_queue(Task.objects, only, exclude).filter(status=Task.Status.RUNNING).update(
        status=Task.Status.FAILED,
        result='Interrumpida: el worker se reinició mientras se ejecutaba',
        finished_at=timezone.now(),
    )


def run_task(task):
    with task_log.capture(task) as log:
        who = f' · {task.created_by.username}' if task.created_by_id else ''
        where = f' · {task.instance.name}' if task.instance_id else ''
        log.set_progress(0, f'{task.get_kind_display()}{where}{who}')
        try:
            task.result = HANDLERS[task.kind](task) or ''
            task.status = Task.Status.DONE
            log.set_progress(100, 'Completada')
        except Exception as e:
            logger.exception('Task %s (%s) failed', task.pk, task.kind)
            task.result = str(e)
            task.status = Task.Status.FAILED
            log.line(f'✖ Fallida: {e}')
            if task.kind == Task.Kind.CREATE_FROM_BACKUP and task.instance_id:
                Instance.objects.filter(pk=task.instance_id).update(status=Instance.Status.ERROR)
        if task.result and task.status == Task.Status.DONE:
            log.line(task.result)
    task.finished_at = timezone.now()
    task.save(update_fields=['status', 'result', 'finished_at'])
    return task


def _create_instance_branch(instance, user, base_branch):
    """Give the instance its own branch (named after it) in its GitHub repo."""
    config = GitHubConfig.objects.filter(user=user).first() if user else None
    if not config or not config.personal_access_token:
        return 'Token de GitHub no configurado: se usa la rama existente'
    ok, message = create_branch(instance.github_repo, base_branch, instance.name, config.personal_access_token)
    if ok:
        instance.github_branch = instance.name
        instance.save(update_fields=['github_branch'])
    return message


def destroy_instance(instance, user=None):
    """Remove an instance completely: containers, volumes, workspace, Traefik config and backup files."""
    from django.conf import settings
    send_instance_notification('deleted', instance, user)
    traefik_config = os.path.join(settings.BASE_DIR, 'traefik', f'instance-{instance.name}.yml')
    if os.path.exists(traefik_config):
        os.remove(traefik_config)
    DockerService().delete_instance(instance)
    for backup_record in instance.backups.all():
        if os.path.exists(backup_record.file_path):
            os.remove(backup_record.file_path)
    from .ai_models import AIAttachment
    for attachment in AIAttachment.objects.filter(message__instance=instance):
        attachment.file.delete(save=False)
    instance.delete()


def backup_all_instances(retention, user=None):
    """Back up every instance and prune old backups. Returns (successes, errors)."""
    service = DockerService()
    successes, errors = [], []
    instances = list(Instance.objects.all())
    for index, instance in enumerate(instances):
        task_log.progress(100 * index // max(len(instances), 1), f'Respaldo de {instance.name} ({index + 1}/{len(instances)})')
        try:
            backup = service.backup_instance(instance, include_filestore=True, user=user)
            successes.append(backup.filename)
        except Exception as e:
            logger.exception('Backup of %s failed', instance.name)
            errors.append(f'{instance.name}: {e}')
            continue
        for old_backup in Backup.objects.filter(instance=instance).order_by('-created_at')[retention:]:
            if os.path.exists(old_backup.file_path):
                os.remove(old_backup.file_path)
            old_backup.delete()
    return successes, errors


@handler(Task.Kind.DEPLOY)
def deploy(task):
    instance = task.instance
    notes = []
    if task.params.get('create_branch') and instance.github_repo and instance.github_branch:
        notes.append(_create_instance_branch(instance, task.created_by, instance.github_branch))
    service = DockerService()
    service.deploy_instance(instance)
    notes += service.deploy_notes
    task_log.progress(95, 'Rutas de Traefik')
    ok, message = TraefikService.generate_instance_config(instance)
    if not ok:
        notes.append(f'Traefik: {message}')
    if task.params.get('notify'):
        send_instance_notification('created', instance, task.created_by)
    return '\n'.join(notes + ['Instancia desplegada'])


@handler(Task.Kind.DUPLICATE)
def duplicate(task):
    source = task.instance
    new_name = task.params['new_name']
    if Instance.objects.filter(name=new_name).exists():
        raise Exception(f'Ya existe una instancia con el nombre "{new_name}"')
    new_instance = DockerService().copy_instance(source, new_name)
    new_instance.owner = source.owner or task.created_by
    new_instance.save(update_fields=['owner'])
    send_instance_notification('created', new_instance, task.created_by)
    return f'Instancia duplicada como "{new_name}"'


@handler(Task.Kind.RENAME)
def rename(task):
    instance = task.instance
    new_name = task.params['new_name']
    if Instance.objects.filter(name=new_name).exclude(pk=instance.pk).exists():
        raise Exception(f'Ya existe una instancia con el nombre "{new_name}"')
    old_name = instance.name
    instance.name = new_name
    DockerService().rename_instance(instance, old_name)
    from .services.domains import build_subdomain
    instance.subdomain = build_subdomain(instance)
    instance.save(update_fields=['subdomain'])
    TraefikService.generate_instance_config(instance)
    return f'Nombre actualizado de "{old_name}" a "{new_name}"'


@handler(Task.Kind.AI_CHAT)
def ai_chat(task):
    from .ai_models import AIMessage
    from .services.ai_assistant import run_turn
    turn = AIMessage.objects.select_related('instance', 'user').get(pk=task.params['turn'])
    origin = task.params.get('odoo')  # asked from an Odoo chatter: answer there too
    try:
        messages = run_turn(turn)
    except Exception as e:
        if origin:
            _reply_in_odoo(turn.instance, origin, f'No pude completar la petición: {e}')
        raise
    answer = next((m.content for m in reversed(messages) if m.content), '')
    if origin:
        installs = _wait_for_installs(turn)
        _reply_in_odoo(turn.instance, origin, '\n\n'.join(filter(None, [answer or 'Hecho.', installs])))
    return answer[:500]


def _wait_for_installs(turn, timeout=900):
    """Outcome of the module installs the turn queued, so the chatter doesn't claim what failed."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        tasks = list(Task.objects.filter(instance=turn.instance, kind=Task.Kind.AI_MODULE, created_at__gte=turn.created_at))
        if all(t.status in (Task.Status.DONE, Task.Status.FAILED) for t in tasks) or time.monotonic() > deadline:
            break
        time.sleep(5)
    lines = []
    # The assistant retries failed installs: report only the last attempt of each module
    latest = {task.params['module']: task for task in sorted(tasks, key=lambda t: t.id)}
    for task in latest.values():
        if task.status == Task.Status.DONE:
            lines.append(f"✅ {task.params['module']}: {task.result.splitlines()[-1] if task.result else 'instalado'}")
        elif task.status == Task.Status.FAILED:
            from .services.ai_assistant import install_error_summary
            lines.append(f"❌ {task.params['module']}: {install_error_summary(task.result, 600)}")
        else:
            lines.append(f"⏳ {task.params['module']}: la instalación sigue en curso")
    return '\n'.join(lines)


def _reply_in_odoo(instance, origin, text):
    from .services.odoo_bridge import post_reply
    try:
        post_reply(instance, origin['db'], origin['model'], origin['res_id'], text)
    except Exception:
        logger.exception('Could not post the AI answer in Odoo for %s', instance.name)


@handler(Task.Kind.ODOO_MIGRATION)
def odoo_migration(task):
    """Copy data from another Odoo over XML-RPC; the log is kept up to date in the task result."""
    from django.core.cache import cache
    from .services.odoo_bridge import odoo_url
    from .services.odoo_migration import Migration, Odoo
    credentials = cache.get(task.params['credentials'])
    cache.delete(task.params['credentials'])  # the passwords are not kept once read
    if not credentials:
        raise Exception('Las credenciales caducaron antes de empezar: vuelve a lanzar la migración')
    lines = []

    def log(text):
        lines.append(text)
        task_log.line(text)
        Task.objects.filter(pk=task.pk).update(result='\n'.join(lines[-300:]))

    source = Odoo(credentials['source_url'], credentials['source_db'], credentials['source_login'], credentials['source_password'])
    log(f"Origen: {credentials['source_url']} (Odoo {source.version}, base de datos {credentials['source_db']})")
    target = Odoo(odoo_url(task.instance), credentials['target_db'], credentials['target_login'], credentials['target_password'])
    log(f"Destino: {task.instance.name} (Odoo {target.version}, base de datos {credentials['target_db']})")
    Migration(source, target, log).run(task.params['steps'])
    return '\n'.join(lines[-300:])


@handler(Task.Kind.BACKUP)
def backup(task):
    record = DockerService().backup_instance(
        task.instance, include_filestore=task.params.get('include_filestore', True), user=task.created_by,
    )
    return f'Backup creado: {record.filename}'


@handler(Task.Kind.RESTORE)
def restore(task):
    file_path = task.params['file_path']
    try:
        DockerService().restore_instance(task.instance, file_path)
    finally:
        # Uploaded files are temporary; backups from the list are kept
        if task.params.get('delete_after') and os.path.exists(file_path):
            os.remove(file_path)
    return f'Respaldo restaurado desde {task.params.get("label") or os.path.basename(file_path)}'


@handler(Task.Kind.CREATE_FROM_BACKUP)
def create_from_backup(task):
    instance = task.instance
    backup_record = Backup.objects.get(pk=task.params['backup_id'])
    notes = []
    if instance.github_repo and instance.github_branch:
        notes.append(_create_instance_branch(instance, task.created_by, instance.github_branch))

    service = DockerService()
    service.deploy_instance(instance)
    task_log.progress(75, f'Restaurando {backup_record.filename}')
    service._wait_for_postgres(service.client.containers.get(f'db_{instance.name}'))
    service.restore_instance(instance, backup_record.file_path)
    instance.status = Instance.Status.RUNNING
    instance.save(update_fields=['status'])
    send_instance_notification('created', instance, task.created_by)
    return '\n'.join(notes + [f'Instancia "{instance.name}" creada desde {backup_record.filename}'])


@handler(Task.Kind.INSTALL_MODULE)
def install_module(task):
    from django.core.files import File
    from .services import OdooModuleService
    file_path = task.params['file_path']
    task_log.progress(10, f"Instalando {task.params.get('label') or 'el módulo'}")
    try:
        with open(file_path, 'rb') as f:
            ok, message, _module_name = OdooModuleService.install_module_from_zip(task.instance, File(f, name=task.params.get('label')))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
    if not ok:
        raise Exception(message)
    return message


@handler(Task.Kind.PULL_REPOS)
def pull_repos(task):
    notes = DockerService().pull_repositories(task.instance)
    return '\n'.join(notes + ['Repositorios actualizados y Odoo reiniciado. Si cambian vistas o datos, actualiza el módulo '
                               'en Odoo (Aplicaciones → Actualizar)'])


@handler(Task.Kind.INSTALL_BROWSER)
def install_browser(task):
    task_log.progress(10, 'Instalando Google Chrome en el contenedor de Odoo')
    return DockerService().install_browser(task.instance)


@handler(Task.Kind.PULL_IMAGE)
def pull_image(task):
    from .services import docker_admin
    task_log.progress(10, f"Descargando {task.params['image']}")
    return f"Imagen descargada: {docker_admin.pull_image(task.params['image'])}"


@handler(Task.Kind.AI_MODULE)
def ai_module(task):
    """Install (-i) or upgrade (-u) a module written by the AI assistant, then restart Odoo."""
    instance = task.instance
    module = task.params['module']
    service = DockerService()
    container = service._get_container(f'odoo_{instance.name}')
    mounts = {m['Destination'] for m in container.attrs.get('Mounts', [])} if container else set()
    notes = []
    if container is None or '/mnt/extra-addons' not in mounts:
        # Older deployments didn't mount the addons folder
        service.deploy_instance(instance)
        container = service._get_container(f'odoo_{instance.name}')
        notes.append('Instancia redesplegada para montar la carpeta de addons')
    db_container = service._get_container(f'db_{instance.name}')
    databases = [instance.database_name] if instance.database_name else service._list_user_databases(db_container)
    if not databases:
        raise Exception('La instancia todavía no tiene base de datos: créala desde Odoo y vuelve a intentarlo')
    flag = '-u' if task.params.get('upgrade') else '-i'
    from .services.docker_service import odoo_command, odoo_major
    for index, database in enumerate(databases):
        task_log.progress(20 + 70 * index // len(databases), f'{"Actualizando" if flag == "-u" else "Instalando"} {module} en {database}')
        extra = ''
        if flag == '-i' and odoo_major(instance.odoo_version) <= 10 and not service.module_known(db_container, database, module):
            # Up to Odoo 10, -i only rescans the addons folders when base is updated too
            if odoo_major(instance.odoo_version) >= 9:
                service.refresh_module_list(instance, container, database)
            else:
                extra = ' -u base'
        result = container.exec_run(f'{odoo_command(instance.odoo_version)} {flag} {module}{extra} -d {database} --stop-after-init', detach=False)
        output = result.output.decode('utf-8', errors='replace')
        if 'invalid module names' in output:
            # Odoo skips a module it can't read (bad manifest, wrong folder) and still exits 0
            raise Exception(f'Odoo no reconoce el módulo {module}: revisa su __manifest__.py y que la carpeta se llame igual')
        if result.exit_code != 0 or 'Traceback' in output:
            # A failed -i/-u leaves modules marked "to install/upgrade": Odoo then skips its crons
            # and reports inconsistent states, so put them back as they were
            db_container.exec_run(['psql', '-U', 'odoo', '-d', database, '-c',
                                   "UPDATE ir_module_module SET state = CASE state WHEN 'to install' THEN 'uninstalled' "
                                   "ELSE 'installed' END WHERE state IN ('to install', 'to upgrade', 'to remove')"],
                                  environment={'PGPASSWORD': 'odoo'})
            task_log.line(output[-20000:])
            raise Exception(f'Error instalando {module} en {database} (la base queda como estaba):\n{output[-3000:]}')
        task_log.line(output[-5000:])
        notes.append(f'{module} {"actualizado" if flag == "-u" else "instalado"} en {database}')
    task_log.progress(95, 'Reiniciando Odoo')
    container.restart()
    return '\n'.join(notes)


@handler(Task.Kind.DELETE_PROJECT)
def delete_project(task):
    from .project_models import Project
    project = Project.objects.filter(pk=task.params['project_id']).first()
    if project is None:
        return 'El proyecto ya no existe'
    names = []
    for instance in project.instances.all():
        destroy_instance(instance, task.created_by)
        names.append(instance.name)
    name = project.name
    project.delete()
    return f'Proyecto «{name}» eliminado' + (f' con sus instancias: {", ".join(names)}' if names else '')


@handler(Task.Kind.BACKUP_ALL)
def backup_all(task):
    successes, errors = backup_all_instances(task.params.get('retention', 5), user=task.created_by)
    if errors and not successes:
        raise Exception('Ningún respaldo se completó:\n' + '\n'.join(errors))
    summary = f'{len(successes)} respaldos completados'
    if errors:
        summary += f', {len(errors)} con errores:\n' + '\n'.join(errors)
    return summary
