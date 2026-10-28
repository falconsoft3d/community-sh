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


def claim_next_task():
    with transaction.atomic():
        task = (
            Task.objects.select_for_update(skip_locked=True)
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


def recover_interrupted_tasks():
    """Tasks left running by a stopped worker will never finish: mark them failed."""
    return Task.objects.filter(status=Task.Status.RUNNING).update(
        status=Task.Status.FAILED,
        result='Interrumpida: el worker se reinició mientras se ejecutaba',
        finished_at=timezone.now(),
    )


def run_task(task):
    try:
        task.result = HANDLERS[task.kind](task) or ''
        task.status = Task.Status.DONE
    except Exception as e:
        logger.exception('Task %s (%s) failed', task.pk, task.kind)
        task.result = str(e)
        task.status = Task.Status.FAILED
        if task.kind == Task.Kind.CREATE_FROM_BACKUP and task.instance_id:
            Instance.objects.filter(pk=task.instance_id).update(status=Instance.Status.ERROR)
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
    instance.delete()


def backup_all_instances(retention, user=None):
    """Back up every instance and prune old backups. Returns (successes, errors)."""
    service = DockerService()
    successes, errors = [], []
    for instance in Instance.objects.all():
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
    if instance.custom_domain:
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
    if instance.custom_domain:
        TraefikService.generate_instance_config(instance)
    return f'Nombre actualizado de "{old_name}" a "{new_name}"'


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
    try:
        with open(file_path, 'rb') as f:
            ok, message, _module_name = OdooModuleService.install_module_from_zip(task.instance, File(f, name=task.params.get('label')))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
    if not ok:
        raise Exception(message)
    return message


@handler(Task.Kind.PULL_IMAGE)
def pull_image(task):
    from .services import docker_admin
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
    for database in databases:
        result = container.exec_run(f'odoo {flag} {module} -d {database} --stop-after-init', detach=False)
        output = result.output.decode('utf-8', errors='replace')
        if result.exit_code != 0 or 'Traceback' in output:
            raise Exception(f'Error instalando {module} en {database}:\n{output[-3000:]}')
        notes.append(f'{module} {"actualizado" if flag == "-u" else "instalado"} en {database}')
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
