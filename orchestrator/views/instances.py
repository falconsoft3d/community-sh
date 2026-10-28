"""Odoo instance management."""
from ..models import Instance
from ..services import DockerService

from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from ..permissions import (
    domain_in_use,
    get_instance_for_user,
    instances_for,
    validate_domain,
    validate_resource_name,
)


@login_required
def dashboard(request):
    """Dashboard view for logged in users"""
    instances = instances_for(request.user).order_by('-created_at')
    return render(request, 'orchestrator/dashboard.html', {'instances': instances})


# Web Views
class InstanceListView(LoginRequiredMixin, ListView):
    model = Instance
    ordering = ['-created_at']

    def get_queryset(self):
        return instances_for(self.request.user).order_by(*self.ordering)


class InstanceCreateView(LoginRequiredMixin, CreateView):
    model = Instance
    from ..forms import InstanceForm
    form_class = InstanceForm
    success_url = reverse_lazy('instance-list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        # Set origin to manual
        form.instance.origin = 'manual'
        form.instance.owner = self.request.user
        # Save the instance first
        response = super().form_valid(form)
        
        # Create GitHub branch if repository is configured
        if self.object.github_repo and self.object.github_branch:
            print("=" * 50)
            print("CREATING GITHUB BRANCH FOR NEW INSTANCE")
            print("=" * 50)
            
            original_branch = self.object.github_branch
            new_branch = self.object.name
            
            print(f"GitHub Repo: {self.object.github_repo}")
            print(f"Original Branch: {original_branch}")
            print(f"New Branch: {new_branch}")
            
            # Get GitHub config
            from ..config_models import GitHubConfig
            github_config = GitHubConfig.objects.filter(user=self.request.user).first()
            
            if github_config and github_config.personal_access_token:
                import subprocess
                import tempfile
                import shutil
                import os
                
                temp_git_dir = tempfile.mkdtemp()
                print(f"Created temp directory: {temp_git_dir}")
                
                try:
                    # Parse repo URL to add token
                    repo_url = self.object.github_repo.replace('https://', f'https://{github_config.personal_access_token}@')
                    print(f"Cloning repository (branch: {original_branch})...")
                    
                    # Clone the repository
                    result = subprocess.run(
                        ['git', 'clone', '--branch', original_branch, '--single-branch', repo_url, temp_git_dir], 
                        check=True, capture_output=True, text=True
                    )
                    print(f"Clone successful")
                    
                    # Create and checkout new branch
                    print(f"Creating new branch: {new_branch}")
                    result = subprocess.run(
                        ['git', 'checkout', '-b', new_branch], 
                        check=True, capture_output=True, text=True, cwd=temp_git_dir
                    )
                    
                    # Push new branch to remote
                    print(f"Pushing branch to remote...")
                    result = subprocess.run(
                        ['git', 'push', 'origin', new_branch], 
                        check=True, capture_output=True, text=True, cwd=temp_git_dir
                    )
                    print(f"✅ Successfully created GitHub branch '{new_branch}'")
                    
                    # Update instance with new branch
                    self.object.github_branch = new_branch
                    self.object.save()
                    print(f"Updated instance branch to: {new_branch}")
                    
                    from django.contrib import messages
                    messages.success(self.request, f'✅ Rama de GitHub "{new_branch}" creada exitosamente')
                    
                except subprocess.CalledProcessError as e:
                    print(f"❌ Git command failed: {e.stderr}")
                    from django.contrib import messages
                    messages.warning(self.request, f'Instancia creada pero no se pudo crear la rama en GitHub')
                except Exception as e:
                    print(f"❌ Unexpected error: {str(e)}")
                finally:
                    if os.path.exists(temp_git_dir):
                        shutil.rmtree(temp_git_dir)
            else:
                print("⚠️ GitHub token not configured")
            
            print("=" * 50)
        
        # Then trigger deployment
        service = DockerService()
        try:
            service.deploy_instance(self.object)
        except Exception as e:
            print(f"Error deploying instance: {e}")
        
        # Send email notification
        from ..email_notifications import send_instance_notification
        send_instance_notification('created', self.object, self.request.user)
        
        return response


class InstanceDetailView(LoginRequiredMixin, DetailView):
    model = Instance

    def get_queryset(self):
        return instances_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = DockerService()
        context['logs'] = service.get_logs(self.object)
        
        # Add backups to context
        from ..backup_models import Backup
        context['backups'] = Backup.objects.filter(instance=self.object).order_by('-created_at')
        
        return context


@login_required
def instance_deploy(request, pk):
    instance = get_instance_for_user(request.user, pk)
    if request.method == 'POST':
        service = DockerService()
        try:
            service.deploy_instance(instance)
            
            # Generate Traefik configuration if instance has custom domain
            if instance.custom_domain:
                from ..traefik_service import TraefikService
                success, msg = TraefikService.generate_instance_config(instance)
                if success:
                    print(f"Traefik config generated for {instance.name}: {msg}", flush=True)
                else:
                    print(f"Warning: Could not generate Traefik config for {instance.name}: {msg}", flush=True)
        except Exception as e:
            print(f"Error deploying: {e}")
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))


@login_required
def instance_stop(request, pk):
    instance = get_instance_for_user(request.user, pk)
    if request.method == 'POST':
        service = DockerService()
        service.stop_instance(instance)
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))


@login_required
def instance_restart(request, pk):
    instance = get_instance_for_user(request.user, pk)
    if request.method == 'POST':
        service = DockerService()
        service.restart_instance(instance)
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))


@login_required
def instance_logs_api(request, pk):
    instance = get_instance_for_user(request.user, pk)
    service = DockerService()
    logs = service.get_logs(instance, lines=200)
    return JsonResponse({'logs': logs})


@login_required
def instance_console_exec(request, pk):
    """Execute commands in the container console"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        command = data.get('command', '')
        
        if not command:
            return JsonResponse({'error': 'No command provided'}, status=400)
        
        try:
            service = DockerService()
            output = service.execute_command(instance, command)
            return JsonResponse({'output': output, 'success': True})
        except Exception as e:
            return JsonResponse({'output': str(e), 'success': False, 'error': str(e)})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def instance_install_requirements(request, pk):
    """Install Python packages from requirements.txt file"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        requirements_file = request.FILES.get('requirements')
        
        if not requirements_file:
            return JsonResponse({'error': 'No requirements file provided'}, status=400)
        
        try:
            # Read file content
            content = requirements_file.read().decode('utf-8')
            lines = content.strip().split('\n')
            
            # Filter out empty lines and comments
            packages = [line.strip() for line in lines if line.strip() and not line.strip().startswith('#')]
            
            if not packages:
                return JsonResponse({'error': 'No packages found in requirements file'}, status=400)
            
            # Install packages one by one and collect output
            service = DockerService()
            outputs = []
            
            outputs.append(f"📦 Instalando {len(packages)} paquete(s)...\n")
            
            for package in packages:
                outputs.append(f"\n→ Instalando {package}...")
                
                # Try pip3 first, then pip
                for pip_cmd in ['pip3', 'pip']:
                    command = f"{pip_cmd} install {package}"
                    output = service.execute_command(instance, command)
                    
                    if '[Exit Code:' not in output or 'Exit Code: 0' in output:
                        outputs.append(f"  ✓ {package} instalado correctamente")
                        break
                else:
                    outputs.append(f"  ✗ Error instalando {package}")
                    outputs.append(f"  {output[:200]}")
            
            outputs.append("\n✓ Proceso de instalación completado")
            
            return JsonResponse({
                'success': True, 
                'output': '\n'.join(outputs)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Error procesando requirements: {str(e)}'
            })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
def instance_configure_domain(request, pk):
    """Configure custom domain for an instance"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        domain = request.POST.get('domain', '').strip()
        
        if not domain:
            messages.error(request, 'El dominio es requerido')
            return redirect('instance-detail', pk=pk)
        
        domain = domain.lower()
        try:
            validate_domain(domain)
        except ValidationError:
            messages.error(request, 'Formato de dominio inválido')
            return redirect('instance-detail', pk=pk)
        if domain_in_use(domain, exclude_instance=instance):
            messages.error(request, f'El dominio {domain} ya está en uso')
            return redirect('instance-detail', pk=pk)
        
        instance.custom_domain = domain
        
        # Check if certificates exist for this domain
        import os
        from django.conf import settings
        
        # Check in production path
        cert_path = f'/opt/community-sh/letsencrypt/live/{domain}/fullchain.pem'
        key_path = f'/opt/community-sh/letsencrypt/live/{domain}/privkey.pem'
        
        # Check in local development path
        if not os.path.exists(cert_path):
            cert_path = os.path.join(settings.BASE_DIR, 'letsencrypt', 'live', domain, 'fullchain.pem')
            key_path = os.path.join(settings.BASE_DIR, 'letsencrypt', 'live', domain, 'privkey.pem')
        
        # If certificates exist, auto-configure SSL
        if os.path.exists(cert_path) and os.path.exists(key_path):
            instance.ssl_enabled = True
            instance.ssl_certificate_path = cert_path
            instance.ssl_key_path = key_path
            print(f"Auto-configured SSL for instance {instance.name} with existing certificates", flush=True)
        else:
            print(f"No certificates found for domain {domain} at {cert_path}", flush=True)
        
        instance.save()
        
        # Generate Traefik configuration for this instance
        from ..traefik_service import TraefikService
        success, msg = TraefikService.generate_instance_config(instance)
        
        if success:
            messages.success(request, f'✅ Dominio {domain} configurado correctamente')
        else:
            messages.warning(request, f'Dominio guardado pero error en Traefik: {msg}')
        
        return redirect('instance-detail', pk=pk)
    
    return redirect('instance-detail', pk=pk)


@login_required
def instance_generate_ssl(request, pk):
    """Generate SSL certificate for instance custom domain"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        if not instance.custom_domain:
            messages.error(request, 'Primero debes configurar un dominio personalizado')
            return redirect('instance-detail', pk=pk)
        
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'El email es requerido')
            return redirect('instance-detail', pk=pk)
        
        try:
            from ..services import SSLService
            ssl_service = SSLService()
            
            # Generate SSL certificate
            success, message, cert_path, key_path = ssl_service.generate_certificate(
                instance.custom_domain, 
                email
            )
            
            if success:
                instance.ssl_enabled = True
                instance.ssl_certificate_path = cert_path
                instance.ssl_key_path = key_path
                instance.ssl_email = email
                instance.save()
                
                messages.success(request, f'✅ Certificado SSL generado correctamente para {instance.custom_domain}')
            else:
                messages.error(request, f'❌ Error al generar certificado: {message}')
                
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        
        return redirect('instance-detail', pk=pk)
    
    return redirect('instance-detail', pk=pk)


@login_required
def instance_update_name(request, pk):
    """Update instance name"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip().lower()
        
        if not new_name:
            messages.error(request, 'El nombre no puede estar vacío')
            return redirect('instance-detail', pk=pk)
        
        try:
            validate_resource_name(new_name)
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('instance-detail', pk=pk)
        
        # Check if name is already taken
        if Instance.objects.filter(name=new_name).exclude(pk=pk).exists():
            messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
            return redirect('instance-detail', pk=pk)
        
        old_name = instance.name
        if new_name == old_name:
            return redirect('instance-detail', pk=pk)
        instance.name = new_name
        
        try:
            DockerService().rename_instance(instance, old_name)
        except Exception as e:
            messages.error(request, f'Error al renombrar la instancia: {str(e)}')
            return redirect('instance-detail', pk=pk)
        
        if instance.custom_domain:
            from ..traefik_service import TraefikService
            TraefikService.generate_instance_config(instance)
        
        messages.success(request, f'Nombre actualizado de "{old_name}" a "{new_name}"')
        return redirect('instance-detail', pk=pk)
    
    return redirect('instance-detail', pk=pk)


@login_required
def instance_install_module(request, pk):
    """Upload and install a module ZIP file"""
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'POST':
        module_file = request.FILES.get('module_file')
        
        if not module_file:
            messages.error(request, 'Debes seleccionar un archivo ZIP del módulo')
            return redirect('instance-detail', pk=pk)
        
        if not module_file.name.endswith('.zip'):
            messages.error(request, 'El archivo debe ser un ZIP')
            return redirect('instance-detail', pk=pk)
        
        if not instance.github_repo:
            messages.error(request, 'Esta instancia no tiene un repositorio de GitHub configurado')
            return redirect('instance-detail', pk=pk)
        
        try:
            from ..services import OdooModuleService
            
            messages.info(request, 'Procesando módulo... Se agregará al repositorio y se desplegará. Esto puede tomar varios minutos.')
            
            # Install module from uploaded ZIP (adds to GitHub repo and deploys)
            success, message, module_name = OdooModuleService.install_module_from_zip(
                instance, 
                module_file
            )
            
            if success:
                messages.success(request, f'✅ {message}')
            else:
                messages.error(request, f'❌ {message}')
                
        except Exception as e:
            messages.error(request, f'Error inesperado: {str(e)}')
        
        return redirect('instance-detail', pk=pk)
    
    return redirect('instance-detail', pk=pk)


@login_required
def instance_delete(request, pk):
    instance = get_instance_for_user(request.user, pk)
    if request.method == 'POST':
        # Send email notification before deleting
        from ..email_notifications import send_instance_notification
        send_instance_notification('deleted', instance, request.user)
        
        # Remove Traefik configuration file if exists
        if instance.custom_domain:
            import os
            from django.conf import settings
            traefik_dir = os.path.join(settings.BASE_DIR, 'traefik')
            config_file = os.path.join(traefik_dir, f'instance-{instance.name}.yml')
            if os.path.exists(config_file):
                os.remove(config_file)
                print(f"Removed Traefik config for {instance.name}", flush=True)
        
        service = DockerService()
        service.delete_instance(instance)
        instance.delete()
        return redirect('instance-list')
    return redirect('instance-detail', pk=pk)


@login_required
def instance_duplicate(request, pk):
    instance = get_instance_for_user(request.user, pk)
    
    if request.method == 'GET':
        # Show the duplication form
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    elif request.method == 'POST':
        # Process the duplication
        new_name = request.POST.get('new_name', '').strip().lower()

        if not new_name:
            from django.contrib import messages
            messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
            return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})

        try:
            validate_resource_name(new_name)
        except ValidationError as e:
            from django.contrib import messages
            messages.error(request, e.messages[0])
            return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
        
        # Check if name already exists
        if Instance.objects.filter(name=new_name).exists():
            from django.contrib import messages
            messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
            return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
        
        # Perform the duplication
        service = DockerService()
        try:
            new_instance = service.copy_instance(instance, new_name)
            new_instance.owner = instance.owner or request.user
            new_instance.save(update_fields=['owner'])
            
            # Send email notification
            from ..email_notifications import send_instance_notification
            send_instance_notification('created', new_instance, request.user)
            
            from django.contrib import messages
            messages.success(request, f'Instancia duplicada exitosamente como "{new_name}"')
            return redirect('instance-detail', pk=new_instance.pk)
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error al duplicar instancia: {str(e)}')
            return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    return redirect('instance-detail', pk=pk)
