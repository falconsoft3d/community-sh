"""Instance backups: create, restore, download and new instances from backups."""
from ..models import Instance

from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
import os
from ..permissions import (
    get_backup_for_user,
    get_instance_for_user,
    validate_database_name,
    validate_resource_name,
)
from ..task_models import Task
from ..tasks import enqueue


@login_required
@require_POST
def instance_backup(request, pk):
    instance = get_instance_for_user(request.user, pk)
    include_filestore = request.POST.get('filestore', 'true') == 'true'
    enqueue(Task.Kind.BACKUP, instance, request.user, include_filestore=include_filestore)
    messages.info(request, 'Respaldo en cola')
    
    if request.POST.get('next') == 'backups':
        return redirect('instance-backups', pk=pk)
    
    # Coming from instance detail: go back to the backups tab
    from django.urls import reverse
    return redirect(reverse('instance-detail', kwargs={'pk': pk}) + '#backups')


@login_required
@require_POST
def instance_restore(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    backup_file = request.FILES.get('backup_file')
    
    if not backup_file:
        messages.error(request, 'No se seleccionó ningún archivo de respaldo')
        return redirect('instance-detail', pk=pk)
    
    # Keep the upload where the worker can read it; the task deletes it afterwards
    from django.conf import settings
    import uuid
    uploads_dir = os.path.join(settings.BASE_DIR, 'backups', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, f'{uuid.uuid4().hex}.zip')
    with open(file_path, 'wb') as f:
        for chunk in backup_file.chunks():
            f.write(chunk)
    
    enqueue(Task.Kind.RESTORE, instance, request.user, file_path=file_path, delete_after=True, label=backup_file.name)
    messages.info(request, 'Restauración en cola')
    return redirect('instance-detail', pk=pk)


@login_required
def instance_backups_list(request, pk):
    instance = get_instance_for_user(request.user, pk)
    from ..backup_models import Backup
    backups = Backup.objects.filter(instance=instance)
    return render(request, 'orchestrator/instance_backups.html', {
        'instance': instance,
        'backups': backups
    })


@login_required
def backup_download(request, backup_id):
    backup = get_backup_for_user(request.user, backup_id)
    
    if not os.path.exists(backup.file_path):
        from django.contrib import messages
        messages.error(request, 'El archivo de respaldo no existe')
        return redirect('instance-backups', pk=backup.instance.pk)
    
    from django.http import FileResponse
    response = FileResponse(open(backup.file_path, 'rb'), as_attachment=True)
    response['Content-Disposition'] = f'attachment; filename="{backup.filename}"'
    return response


@login_required
def backup_delete(request, backup_id):
    backup = get_backup_for_user(request.user, backup_id, manage=True)
    instance_pk = backup.instance.pk
    
    if request.method == 'POST':
        # Delete the file
        if os.path.exists(backup.file_path):
            os.remove(backup.file_path)
        
        # Delete the record
        backup.delete()
        
        from django.contrib import messages
        messages.success(request, 'Respaldo eliminado exitosamente')
    
    return redirect('instance-backups', pk=instance_pk)


@login_required
@require_POST
def backup_restore_action(request, backup_id):
    backup = get_backup_for_user(request.user, backup_id, manage=True)
    enqueue(Task.Kind.RESTORE, backup.instance, request.user, file_path=backup.file_path, label=backup.filename)
    messages.info(request, f'Restauración desde {backup.filename} en cola')
    return redirect('instance-backups', pk=backup.instance.pk)


@login_required
def backup_create_instance(request, backup_id):
    """Create a new instance from a backup"""
    backup = get_backup_for_user(request.user, backup_id, manage=True)
    
    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip().lower()
        
        if not new_name:
            messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
            return redirect('instance-backups', pk=backup.instance.pk)
        
        try:
            validate_resource_name(new_name)
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('instance-backups', pk=backup.instance.pk)
        
        if Instance.objects.filter(name=new_name).exists():
            messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
            return redirect('instance-backups', pk=backup.instance.pk)
        
        try:
            from ..services.docker_service import read_backup_metadata
            metadata = read_backup_metadata(backup.file_path)
            
            # Use the same database name from the original backup
            original_db_name = metadata.get('database_name') or new_name.replace('-', '_')
            validate_database_name(original_db_name)
        except (Exception, ValidationError) as e:
            messages.error(request, f'No se pudo leer el respaldo: {e}')
            return redirect('instance-backups', pk=backup.instance.pk)
        
        new_instance = Instance.objects.create(
            name=new_name,
            odoo_version=metadata.get('odoo_version') or backup.instance.odoo_version,
            github_repo=backup.instance.github_repo,
            github_branch=backup.instance.github_branch,
            database_name=original_db_name,
            status=Instance.Status.DEPLOYING,
            origin='backup',
            owner=backup.instance.owner or request.user,
            project=backup.instance.project,
        )
        # The worker creates the GitHub branch, deploys and restores the backup
        enqueue(Task.Kind.CREATE_FROM_BACKUP, new_instance, request.user, backup_id=backup.pk)
        messages.info(request, f'Creación de "{new_name}" desde el respaldo en cola')
        return redirect('instance-detail', pk=new_instance.pk)
    
    # GET request - show form
    # Generate suggested name
    base_name = backup.instance.name
    suggested_name = f"{base_name}-copy-1"
    counter = 1
    
    # Find next available copy number
    while Instance.objects.filter(name=suggested_name).exists():
        counter += 1
        suggested_name = f"{base_name}-copy-{counter}"
    
    return render(request, 'orchestrator/backup_create_instance.html', {
        'backup': backup,
        'source_instance': backup.instance,
        'suggested_name': suggested_name
    })


@login_required
def backup_list(request):
    """All backups the user can see, newest first, optionally filtered by project."""
    from ..backup_models import Backup
    from ..permissions import can_manage, instances_for, projects_for
    backups = Backup.objects.filter(instance__in=instances_for(request.user)).select_related('instance__project')
    selected_project = request.GET.get('project', '')
    if selected_project:
        backups = backups.filter(instance__project_id=selected_project)
    backups = list(backups.order_by('-created_at')[:200])
    for backup in backups:
        backup.can_manage = can_manage(request.user, backup.instance)
    from ..permissions import managed_projects_for
    return render(request, 'orchestrator/backup_list.html', {
        'backups': backups,
        'managed_projects': managed_projects_for(request.user),
        'odoo_versions': [v for v, _ in Instance._meta.get_field('odoo_version').choices],
        'projects': projects_for(request.user),
        'selected_project': selected_project,
        'total_size': sum(b.file_size for b in backups),
    })



@login_required
@require_POST
def backup_import(request):
    """Upload a backup (panel ZIP, Odoo database-manager ZIP or .dump) and create an instance from it."""
    import uuid
    from django.conf import settings
    from ..backup_models import Backup
    from ..permissions import is_client, managed_projects_for
    from ..services.docker_service import read_backup_metadata

    if is_client(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    upload = request.FILES.get('backup_file')
    name = request.POST.get('name', '').strip().lower()
    project = managed_projects_for(request.user).filter(pk=request.POST.get('project') or 0).first()
    try:
        validate_resource_name(name)
    except ValidationError as e:
        messages.error(request, e.messages[0])
        return redirect('backup-list')
    if not upload or project is None:
        messages.error(request, 'Elige un archivo y un proyecto')
        return redirect('backup-list')
    if Instance.objects.filter(name=name).exists():
        messages.error(request, f'Ya existe una instancia con el nombre "{name}"')
        return redirect('backup-list')

    backups_dir = os.path.join(settings.BASE_DIR, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    file_path = os.path.join(backups_dir, f'imported_{name}_{uuid.uuid4().hex[:8]}{os.path.splitext(upload.name)[1] or ".zip"}')
    with open(file_path, 'wb') as f:
        for chunk in upload.chunks():
            f.write(chunk)
    try:
        metadata = read_backup_metadata(file_path)
        database_name = metadata['database_name'] or name.replace('-', '_')
        validate_database_name(database_name)
    except (Exception, ValidationError) as e:
        os.remove(file_path)
        messages.error(request, f'No se pudo leer el respaldo: {e}')
        return redirect('backup-list')

    odoo_version = request.POST.get('odoo_version') or metadata['odoo_version']
    valid_versions = {value for value, _ in Instance._meta.get_field('odoo_version').choices}
    if odoo_version not in valid_versions:
        os.remove(file_path)
        messages.error(request, 'No se pudo detectar la versión de Odoo del respaldo: elígela en el formulario')
        return redirect('backup-list')

    instance = Instance.objects.create(
        name=name, odoo_version=odoo_version, database_name=database_name, project=project,
        owner=project.owner if request.user.is_superuser else request.user,
        status=Instance.Status.DEPLOYING, origin='backup',
    )
    backup = Backup.objects.create(
        instance=instance, filename=upload.name, file_path=file_path, file_size=os.path.getsize(file_path),
        include_filestore=metadata['has_filestore'], created_by=request.user,
    )
    enqueue(Task.Kind.CREATE_FROM_BACKUP, instance, request.user, backup_id=backup.pk)
    formats = {'panel': 'backup del panel', 'odoo': 'backup de Odoo', 'pg_dump': 'volcado de PostgreSQL (sin filestore)'}
    messages.info(request, f'Importando {formats[metadata["format"]]} como «{name}» (Odoo {odoo_version}). Sigue el progreso en la instancia.')
    return redirect('instance-detail', pk=instance.pk)
