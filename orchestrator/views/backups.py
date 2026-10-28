"""Instance backups: create, restore, download and new instances from backups."""
from ..models import Instance
from ..services import DockerService

from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
import os
from ..permissions import (
    get_backup_for_user,
    get_instance_for_user,
    validate_resource_name,
)


@login_required
@require_POST
def instance_backup(request, pk):
    instance = get_instance_for_user(request.user, pk)
    include_filestore = request.POST.get('filestore', 'true') == 'true'
    
    try:
        service = DockerService()
        backup_record = service.backup_instance(instance, include_filestore=include_filestore, user=request.user)
        
        from django.contrib import messages
        messages.success(request, f'Backup creado exitosamente: {backup_record.filename}')
    except Exception as e:
        from django.contrib import messages
        messages.error(request, f'Error creating backup: {str(e)}')
    
    if request.POST.get('next') == 'backups':
        return redirect('instance-backups', pk=pk)
    
    # Coming from instance detail: go back to the backups tab
    from django.urls import reverse
    return redirect(reverse('instance-detail', kwargs={'pk': pk}) + '#backups')


@login_required
def instance_restore(request, pk):
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        backup_file = request.FILES.get('backup_file')
        
        if not backup_file:
            from django.contrib import messages
            messages.error(request, 'No se seleccionó ningún archivo de respaldo')
            return redirect('instance-detail', pk=pk)
        
        # Save uploaded file temporarily
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        for chunk in backup_file.chunks():
            temp_file.write(chunk)
        temp_file.close()
        
        try:
            service = DockerService()
            service.restore_instance(instance, temp_file.name)
            
            from django.contrib import messages
            messages.success(request, 'Respaldo restaurado exitosamente')
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error restaurando respaldo: {str(e)}')
        finally:
            # Clean up temp file
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)
    
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
    backup = get_backup_for_user(request.user, backup_id)
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
def backup_restore_action(request, backup_id):
    backup = get_backup_for_user(request.user, backup_id)
    instance = backup.instance
    
    if request.method == 'POST':
        try:
            service = DockerService()
            service.restore_instance(instance, backup.file_path)
            
            from django.contrib import messages
            messages.success(request, f'Respaldo restaurado exitosamente desde {backup.filename}')
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error restaurando respaldo: {str(e)}')
    
    return redirect('instance-backups', pk=instance.pk)


@login_required
def backup_create_instance(request, backup_id):
    """Create a new instance from a backup"""
    import zipfile
    import json
    
    backup = get_backup_for_user(request.user, backup_id)
    
    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip().lower()

        if not new_name:
            from django.contrib import messages
            messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
            return redirect('instance-backups', pk=backup.instance.pk)

        try:
            validate_resource_name(new_name)
        except ValidationError as e:
            from django.contrib import messages
            messages.error(request, e.messages[0])
            return redirect('instance-backups', pk=backup.instance.pk)
        
        # Check if name already exists
        if Instance.objects.filter(name=new_name).exists():
            from django.contrib import messages
            messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
            return redirect('instance-backups', pk=backup.instance.pk)
        
        try:
            # Read metadata from backup
            with zipfile.ZipFile(backup.file_path, 'r') as zipf:
                metadata_content = zipf.read('metadata.json')
                metadata = json.loads(metadata_content)
            
            # Find an available port
            import random
            used_ports = list(Instance.objects.values_list('port', flat=True))
            while True:
                port = random.randint(8000, 9000)
                if port not in used_ports:
                    break
            
            # Use the same database name from the original backup
            original_db_name = metadata.get('database_name')
            if not original_db_name:
                # Fallback: usar el nombre de la instancia si no hay metadata
                original_db_name = new_name.replace('-', '_')
            from ..permissions import validate_database_name
            validate_database_name(original_db_name)
            
            # Create new instance
            new_instance = Instance.objects.create(
                name=new_name,
                odoo_version=metadata.get('odoo_version', backup.instance.odoo_version),
                github_repo=metadata.get('github_repo', backup.instance.github_repo),
                github_branch=metadata.get('github_branch', backup.instance.github_branch),
                database_name=original_db_name,
                port=port,
                status='deploying',
                origin='backup',
                owner=backup.instance.owner or request.user,
            )
            
            from django.contrib import messages
            
            # Create new branch in GitHub from original branch BEFORE deploying
            print("=" * 50)
            print("STARTING GITHUB BRANCH CREATION")
            print("=" * 50)
            
            original_branch = metadata.get('github_branch', 'main')
            new_branch = new_name
            github_repo = metadata.get('github_repo', '')
            
            print(f"GitHub Repo: {github_repo}")
            print(f"Original Branch: {original_branch}")
            print(f"New Branch: {new_branch}")
            
            if github_repo:
                print(f"Repository URL exists, proceeding with branch creation...")
                
                # Get GitHub config
                from ..config_models import GitHubConfig
                github_config = GitHubConfig.objects.filter(user=request.user).first()
                
                if github_config:
                    print(f"GitHub config found for user: {request.user.username}")
                    print(f"Has token: {bool(github_config.personal_access_token)}")
                else:
                    print("No GitHub config found")
                
                if github_config and github_config.personal_access_token:
                    import subprocess
                    import tempfile
                    import shutil
                    
                    # Create temp directory for git operations
                    temp_git_dir = tempfile.mkdtemp()
                    print(f"Created temp directory: {temp_git_dir}")
                    
                    try:
                        # Parse repo URL to add token
                        repo_url = github_repo.replace('https://', f'https://{github_config.personal_access_token}@')
                        print(f"Cloning repository (branch: {original_branch})...")
                        
                        # Clone the repository
                        result = subprocess.run(
                            ['git', 'clone', '--branch', original_branch, '--single-branch', repo_url, temp_git_dir], 
                            check=True, capture_output=True, text=True
                        )
                        print(f"Clone output: {result.stdout}")
                        print(f"Clone successful")
                        
                        # Create and checkout new branch
                        print(f"Creating new branch: {new_branch}")
                        result = subprocess.run(
                            ['git', 'checkout', '-b', new_branch], 
                            check=True, capture_output=True, text=True, cwd=temp_git_dir
                        )
                        print(f"Checkout output: {result.stdout}")
                        
                        # Push new branch to remote
                        print(f"Pushing branch to remote...")
                        result = subprocess.run(
                            ['git', 'push', 'origin', new_branch], 
                            check=True, capture_output=True, text=True, cwd=temp_git_dir
                        )
                        print(f"Push output: {result.stdout}")
                        print(f"✅ Successfully created GitHub branch '{new_branch}'")
                        
                        # Update instance with new branch BEFORE deploying
                        new_instance.github_branch = new_branch
                        new_instance.save()
                        print(f"Updated instance branch to: {new_branch}")
                        
                        messages.success(request, f'✅ Rama de GitHub "{new_branch}" creada exitosamente')
                        
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Git command failed!")
                        print(f"Error: {e.stderr}")
                        print(f"Return code: {e.returncode}")
                        messages.warning(request, f'Instancia creada pero no se pudo crear la rama en GitHub: {e.stderr}')
                    except Exception as e:
                        print(f"❌ Unexpected error: {str(e)}")
                        import traceback
                        print(traceback.format_exc())
                        messages.warning(request, f'Error al crear rama en GitHub: {str(e)}')
                    finally:
                        # Clean up temp directory
                        if os.path.exists(temp_git_dir):
                            print(f"Cleaning up temp directory: {temp_git_dir}")
                            shutil.rmtree(temp_git_dir)
                else:
                    print("⚠️ GitHub token not configured, skipping branch creation")
                    messages.info(request, 'Configure su token de GitHub en Settings para crear ramas automáticamente.')
            else:
                print("⚠️ No GitHub repository configured for this instance")
            
            print("=" * 50)
            print("GITHUB BRANCH CREATION FINISHED")
            print("=" * 50)
            
            # NOW deploy the instance (it will use the new branch)
            service = DockerService()
            print(f"Deploying instance {new_name} with branch {new_instance.github_branch}...")
            service.deploy_instance(new_instance)
            
            # Wait for containers to be ready
            import time
            print("Waiting for containers to be ready...")
            time.sleep(5)  # Wait 5 seconds for containers to start
            
            # Restore the backup to the new instance
            print(f"Restoring backup {backup.filename} to instance {new_name}...")
            service.restore_instance(new_instance, backup.file_path)
            
            # Update instance status
            new_instance.status = 'running'
            new_instance.save()
            
            # Send email notification
            from ..email_notifications import send_instance_notification
            send_instance_notification('created', new_instance, request.user)
            
            messages.success(request, f'Nueva instancia "{new_name}" creada exitosamente desde el backup')
            return redirect('instance-detail', pk=new_instance.pk)
            
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error creando instancia desde backup: {str(e)}')
            # Clean up if instance was created
            if 'new_instance' in locals():
                new_instance.delete()
            return redirect('instance-backups', pk=backup.instance.pk)
    
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
