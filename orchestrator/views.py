from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Instance
from .serializers import InstanceSerializer
from .services import DockerService

# Web Views imports
from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.shortcuts import redirect, get_object_or_404, render
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import os

# API ViewSet
class InstanceViewSet(viewsets.ModelViewSet):
    queryset = Instance.objects.all()
    serializer_class = InstanceSerializer

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        instance = self.get_object()
        service = DockerService()
        try:
            service.deploy_instance(instance)
            serializer = self.get_serializer(instance)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        instance = self.get_object()
        service = DockerService()
        service.stop_instance(instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

# Home view
def home(request):
    """Home/landing page"""
    from .config_models import GitHubConfig
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = GitHubConfig.objects.first()
        if config and not config.public_website_enabled:
            # If user is already authenticated, go to dashboard
            if request.user.is_authenticated:
                return redirect('instance-list')
            # Otherwise redirect to login
            return redirect('login')
    except:
        pass
    
    from .blog_models import BlogPost
    featured_posts = BlogPost.objects.filter(published=True, featured=True)[:3]
    return render(request, 'orchestrator/home.html', {'featured_posts': featured_posts})

@login_required
def dashboard(request):
    """Dashboard view for logged in users"""
    instances = Instance.objects.all().order_by('-created_at')
    return render(request, 'orchestrator/dashboard.html', {'instances': instances})

def blog_list(request):
    """Blog list page"""
    from .config_models import GitHubConfig
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = GitHubConfig.objects.first()
        if config and not config.public_website_enabled:
            if request.user.is_authenticated:
                return redirect('instance-list')
            return redirect('login')
    except:
        pass
    
    from .blog_models import BlogPost
    posts = BlogPost.objects.filter(published=True)
    return render(request, 'orchestrator/blog_list.html', {'posts': posts})

def blog_detail(request, slug):
    """Blog post detail page"""
    from .config_models import GitHubConfig
    from django.shortcuts import redirect
    
    # Check if public website is enabled
    try:
        config = GitHubConfig.objects.first()
        if config and not config.public_website_enabled:
            if request.user.is_authenticated:
                return redirect('instance-list')
            return redirect('login')
    except:
        pass
    
    from .blog_models import BlogPost
    post = get_object_or_404(BlogPost, slug=slug, published=True)
    
    # Render markdown to HTML
    import markdown
    from markdown.extensions.codehilite import CodeHiliteExtension
    from markdown.extensions.fenced_code import FencedCodeExtension
    
    md = markdown.Markdown(extensions=[
        'extra',
        'codehilite',
        'fenced_code',
        'tables',
        'toc'
    ])
    post.html_content = md.convert(post.content)
    
    return render(request, 'orchestrator/blog_detail.html', {'post': post})

# Web Views
class InstanceListView(LoginRequiredMixin, ListView):
    model = Instance
    ordering = ['-created_at']

class InstanceCreateView(LoginRequiredMixin, CreateView):
    model = Instance
    from .forms import InstanceForm
    form_class = InstanceForm
    success_url = reverse_lazy('instance-list')
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        # Set origin to manual
        form.instance.origin = 'manual'
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
            from .config_models import GitHubConfig
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
        from .email_notifications import send_instance_notification
        send_instance_notification('created', self.object, self.request.user)
        
        return response

class InstanceDetailView(LoginRequiredMixin, DetailView):
    model = Instance

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = DockerService()
        context['logs'] = service.get_logs(self.object)
        
        # Add backups to context
        from .backup_models import Backup
        context['backups'] = Backup.objects.filter(instance=self.object).order_by('-created_at')
        
        return context

@login_required
def instance_deploy(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    if request.method == 'POST':
        service = DockerService()
        try:
            service.deploy_instance(instance)
            
            # Generate Traefik configuration if instance has custom domain
            if instance.custom_domain:
                from .traefik_service import TraefikService
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
    instance = get_object_or_404(Instance, pk=pk)
    if request.method == 'POST':
        service = DockerService()
        service.stop_instance(instance)
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))

@login_required
def instance_restart(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    if request.method == 'POST':
        service = DockerService()
        service.restart_instance(instance)
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))

@login_required
def instance_logs_api(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    service = DockerService()
    logs = service.get_logs(instance, lines=200)
    return JsonResponse({'logs': logs})

@login_required
def instance_console_exec(request, pk):
    """Execute commands in the container console"""
    instance = get_object_or_404(Instance, pk=pk)
    
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
    instance = get_object_or_404(Instance, pk=pk)
    
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
    instance = get_object_or_404(Instance, pk=pk)
    
    if request.method == 'POST':
        domain = request.POST.get('domain', '').strip()
        
        if not domain:
            messages.error(request, 'El dominio es requerido')
            return redirect('instance-detail', pk=pk)
        
        # Basic domain validation
        import re
        domain_pattern = r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$'
        if not re.match(domain_pattern, domain.lower()):
            messages.error(request, 'Formato de dominio inválido')
            return redirect('instance-detail', pk=pk)
        
        instance.custom_domain = domain
        
        # Check if certificates exist for this domain in GitHubConfig
        from .config_models import GitHubConfig
        try:
            config = GitHubConfig.objects.get(user=request.user)
            # If the domain matches and there are certificates, copy them to the instance
            if config.main_domain == domain and config.ssl_certificate_path and config.ssl_key_path:
                import os
                if os.path.exists(config.ssl_certificate_path) and os.path.exists(config.ssl_key_path):
                    instance.ssl_enabled = True
                    instance.ssl_certificate_path = config.ssl_certificate_path
                    instance.ssl_key_path = config.ssl_key_path
                    instance.ssl_email = config.ssl_email
                    print(f"Auto-configured SSL for instance {instance.name} from GitHubConfig", flush=True)
        except GitHubConfig.DoesNotExist:
            pass
        
        instance.save()
        
        # Generate Traefik configuration for this instance
        from .traefik_service import TraefikService
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
    instance = get_object_or_404(Instance, pk=pk)
    
    if request.method == 'POST':
        if not instance.custom_domain:
            messages.error(request, 'Primero debes configurar un dominio personalizado')
            return redirect('instance-detail', pk=pk)
        
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'El email es requerido')
            return redirect('instance-detail', pk=pk)
        
        try:
            from .services import SSLService
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
    instance = get_object_or_404(Instance, pk=pk)
    
    if request.method == 'POST':
        new_name = request.POST.get('name', '').strip().lower()
        
        if not new_name:
            messages.error(request, 'El nombre no puede estar vacío')
            return redirect('instance-detail', pk=pk)
        
        # Validate name format (lowercase, numbers, hyphens only)
        import re
        if not re.match(r'^[a-z0-9-]+$', new_name):
            messages.error(request, 'El nombre solo puede contener letras minúsculas, números y guiones')
            return redirect('instance-detail', pk=pk)
        
        # Check if name is already taken
        if Instance.objects.filter(name=new_name).exclude(pk=pk).exists():
            messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
            return redirect('instance-detail', pk=pk)
        
        old_name = instance.name
        instance.name = new_name
        instance.save()
        
        messages.success(request, f'Nombre actualizado de "{old_name}" a "{new_name}". Considera redesplegar la instancia para aplicar los cambios.')
        return redirect('instance-detail', pk=pk)
    
    return redirect('instance-detail', pk=pk)

@login_required
def instance_install_module(request, pk):
    """Upload and install a module ZIP file"""
    instance = get_object_or_404(Instance, pk=pk)
    
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
            from .services import OdooModuleService
            
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
    instance = get_object_or_404(Instance, pk=pk)
    if request.method == 'POST':
        # Send email notification before deleting
        from .email_notifications import send_instance_notification
        send_instance_notification('deleted', instance, request.user)
        
        # Remove Traefik configuration file if exists
        if instance.custom_domain:
            from .traefik_service import TraefikService
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
    instance = get_object_or_404(Instance, pk=pk)
    
    if request.method == 'GET':
        # Show the duplication form
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    elif request.method == 'POST':
        # Process the duplication
        new_name = request.POST.get('new_name', '').strip()
        
        if not new_name:
            from django.contrib import messages
            messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
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
            
            # Send email notification
            from .email_notifications import send_instance_notification
            send_instance_notification('created', new_instance, request.user)
            
            from django.contrib import messages
            messages.success(request, f'Instancia duplicada exitosamente como "{new_name}"')
            return redirect('instance-detail', pk=new_instance.pk)
        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error al duplicar instancia: {str(e)}')
            return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    return redirect('instance-detail', pk=pk)

@login_required
def metrics_view(request):
    import psutil
    import docker
    from django.db.models import Count
    
    # System metrics
    cpu_percent = round(psutil.cpu_percent(interval=1), 2)
    cpu_count = psutil.cpu_count()
    
    memory = psutil.virtual_memory()
    memory_percent = round(memory.percent, 2)
    memory_used_gb = round(memory.used / (1024**3), 2)
    memory_total_gb = round(memory.total / (1024**3), 2)
    
    disk = psutil.disk_usage('/')
    disk_percent = round(disk.percent, 2)
    disk_used_gb = round(disk.used / (1024**3), 2)
    disk_total_gb = round(disk.total / (1024**3), 2)
    
    # Docker metrics
    client = docker.from_env()
    containers = client.containers.list(all=True)
    containers_running = len([c for c in containers if c.status == 'running'])
    containers_total = len(containers)
    
    docker_info = client.info()
    docker_version = client.version()['Version']
    docker_images = len(client.images.list())
    docker_networks = len(client.networks.list())
    
    # Instance status counts
    status_counts = Instance.objects.values('status').annotate(count=Count('id'))
    instances_running = next((item['count'] for item in status_counts if item['status'] == 'running'), 0)
    instances_deploying = next((item['count'] for item in status_counts if item['status'] == 'deploying'), 0)
    instances_stopped = next((item['count'] for item in status_counts if item['status'] == 'stopped'), 0)
    instances_error = next((item['count'] for item in status_counts if item['status'] == 'error'), 0)
    
    # Container resource usage stats
    container_stats = []
    running_containers = client.containers.list()
    for container in running_containers:
        try:
            stats = container.stats(stream=False)
            
            # Calculate CPU percentage
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
            cpu_percent = 0.0
            if system_delta > 0 and cpu_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', [1])) * 100.0
            
            # Calculate memory usage
            memory_usage = stats['memory_stats'].get('usage', 0)
            memory_limit = stats['memory_stats'].get('limit', 1)
            memory_percent = (memory_usage / memory_limit) * 100 if memory_limit > 0 else 0
            
            # Network I/O
            network_rx = 0
            network_tx = 0
            if 'networks' in stats:
                for interface, data in stats['networks'].items():
                    network_rx += data.get('rx_bytes', 0)
                    network_tx += data.get('tx_bytes', 0)
            
            container_stats.append({
                'name': container.name,
                'cpu_percent': round(cpu_percent, 2),
                'memory_percent': round(memory_percent, 2),
                'memory_usage': f"{round(memory_usage / (1024**2), 2)} MB",
                'memory_limit': f"{round(memory_limit / (1024**2), 2)} MB",
                'network_rx': f"{round(network_rx / (1024**2), 2)} MB",
                'network_tx': f"{round(network_tx / (1024**2), 2)} MB",
            })
        except Exception as e:
            print(f"Error getting stats for {container.name}: {e}")
            continue
    
    context = {
        'metrics': {
            'cpu_percent': cpu_percent,
            'cpu_count': cpu_count,
            'memory_percent': memory_percent,
            'memory_used_gb': memory_used_gb,
            'memory_total_gb': memory_total_gb,
            'disk_percent': disk_percent,
            'disk_used_gb': disk_used_gb,
            'disk_total_gb': disk_total_gb,
            'containers_running': containers_running,
            'containers_total': containers_total,
            'docker_version': docker_version,
            'docker_images': docker_images,
            'docker_networks': docker_networks,
            'instances_running': instances_running,
            'instances_deploying': instances_deploying,
            'instances_stopped': instances_stopped,
            'instances_error': instances_error,
        },
        'container_stats': container_stats,
    }
    
    return render(request, 'orchestrator/metrics.html', context)

@login_required
def settings_view(request):
    from .config_models import GitHubConfig
    from django.contrib import messages
    
    # Get or create GitHub config for the user
    config, created = GitHubConfig.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Debug: print all POST data
        import sys
        print("=== POST DATA ===", file=sys.stderr)
        for key, value in request.POST.items():
            print(f"{key}: {value}", file=sys.stderr)
        print("=================", file=sys.stderr)
        
        # Update configuration based on which fields are present in POST
        # This allows each tab to submit independently without affecting others
        
        # Update GitHub configuration if present
        if 'personal_access_token' in request.POST:
            config.personal_access_token = request.POST.get('personal_access_token', '')
            config.default_organization = request.POST.get('default_organization', '')
            config.webhook_secret = request.POST.get('webhook_secret', '')
        
        # Update general settings if present
        if 'registration_enabled' in request.POST or request.POST.get('registration_enabled') == 'on':
            config.registration_enabled = request.POST.get('registration_enabled') == 'on'
        if 'public_website_enabled' in request.POST or request.POST.get('public_website_enabled') == 'on':
            config.public_website_enabled = request.POST.get('public_website_enabled') == 'on'
        if 'two_factor_required' in request.POST or request.POST.get('two_factor_required') == 'on':
            config.two_factor_required = request.POST.get('two_factor_required') == 'on'
        
        # Update email notifications if present
        if 'email_notifications_enabled' in request.POST or request.POST.get('email_notifications_enabled') == 'on':
            config.email_notifications_enabled = request.POST.get('email_notifications_enabled') == 'on'
        if 'notification_emails' in request.POST:
            config.notification_emails = request.POST.get('notification_emails', '')
        
        # Update automatic backups configuration if present
        if 'auto_backup_enabled' in request.POST or request.POST.get('auto_backup_enabled') == 'on':
            config.auto_backup_enabled = request.POST.get('auto_backup_enabled') == 'on'
        if 'auto_backup_frequency_unit' in request.POST:
            config.auto_backup_frequency_unit = request.POST.get('auto_backup_frequency_unit', 'day')
        if 'auto_backup_frequency_value' in request.POST:
            config.auto_backup_frequency_value = int(request.POST.get('auto_backup_frequency_value', 5))
        if 'auto_backup_retention' in request.POST:
            config.auto_backup_retention = int(request.POST.get('auto_backup_retention', 5))
        
        # Update domain and SSL configuration if present
        old_domain = config.main_domain
        old_ssl_enabled = config.ssl_enabled
        
        # Check which section is being saved
        section = request.POST.get('section', '')
        
        if section == 'domain':
            # Update domain and SSL when saving Domain & SSL section
            config.main_domain = request.POST.get('main_domain', '').strip()
            # Checkboxes not checked don't appear in POST, so we need to check explicitly
            config.ssl_enabled = 'ssl_enabled' in request.POST
            
            # If domain is removed, also clear SSL settings
            if not config.main_domain:
                config.ssl_enabled = False
                config.ssl_certificate_path = ''
                config.ssl_key_path = ''
                config.ssl_email = ''
        
        config.save()
        
        # Update Traefik configuration if domain or SSL settings changed
        # Also update if domain was removed (changed from something to empty)
        if section == 'domain' and (old_domain != config.main_domain or old_ssl_enabled != config.ssl_enabled):
            from .traefik_service import TraefikService
            # Generate dynamic Traefik configuration
            success, msg = TraefikService.generate_dynamic_config(
                domain=config.main_domain if config.main_domain else None,
                ssl_enabled=config.ssl_enabled,
                cert_path=config.ssl_certificate_path if config.ssl_enabled else None,
                key_path=config.ssl_key_path if config.ssl_enabled else None
            )
            if success:
                if config.main_domain:
                    protocol = "HTTPS" if config.ssl_enabled and config.ssl_certificate_path else "HTTP"
                    messages.info(request, f'✅ Dominio {config.main_domain} configurado con {protocol}. Traefik lo detectará automáticamente.')
                else:
                    messages.info(request, 'Dominio eliminado, volviendo a localhost.')
            else:
                messages.warning(request, f'Configuración guardada, pero hubo un problema con Traefik: {msg}')
        
        messages.success(request, 'Settings saved successfully')
        return redirect('settings')
    
    return render(request, 'orchestrator/settings.html', {'config': config})

@login_required
def run_auto_backups_view(request):
    """Execute automatic backups for all instances"""
    from django.contrib import messages
    from .config_models import GitHubConfig
    from .services import DockerService
    from .backup_models import Backup
    import traceback
    
    try:
        # Get config from current user
        config = GitHubConfig.objects.filter(user=request.user).first()
        if not config:
            messages.error(request, 'No se encontró la configuración')
            return redirect('settings')
        
        # Get all running instances
        instances = Instance.objects.filter(status='running')
        if not instances.exists():
            messages.info(request, 'No hay instancias en ejecución para respaldar')
            return redirect('settings')
        
        print(f"Starting manual backup for {instances.count()} instances...")
        docker_service = DockerService()
        success_count = 0
        error_count = 0
        errors = []
        
        for instance in instances:
            try:
                print(f"Backing up instance: {instance.name}")
                # Create backup with filestore
                backup_record = docker_service.backup_instance(instance, include_filestore=True)
                success_count += 1
                print(f"Backup created for {instance.name}: {backup_record.filename}")
                
                # Clean old backups based on retention policy (per instance)
                retention = config.auto_backup_retention if config.auto_backup_retention else 5
                instance_backups = Backup.objects.filter(instance=instance).order_by('-created_at')
                
                print(f"Instance {instance.name} has {instance_backups.count()} backups, retention limit: {retention}")
                
                if instance_backups.count() > retention:
                    old_backups = instance_backups[retention:]
                    for old_backup in old_backups:
                        try:
                            import os
                            if os.path.exists(old_backup.file_path):
                                os.remove(old_backup.file_path)
                                print(f"Deleted old backup file: {old_backup.file_path}")
                            old_backup.delete()
                            print(f"Deleted old backup record: {old_backup.filename}")
                        except Exception as e:
                            print(f"Error deleting old backup {old_backup.filename}: {str(e)}")
                
            except Exception as e:
                error_count += 1
                error_msg = f"{instance.name}: {str(e)}"
                errors.append(error_msg)
                print(f"Error backing up instance {instance.name}: {str(e)}")
                print(traceback.format_exc())
        
        # Show results
        if success_count > 0 and error_count == 0:
            messages.success(request, f'✅ Respaldos completados exitosamente: {success_count} instancias respaldadas')
        elif success_count > 0 and error_count > 0:
            messages.warning(request, f'⚠️ Respaldos parciales: {success_count} exitosos, {error_count} con errores')
            for error in errors[:3]:  # Show first 3 errors
                messages.error(request, f'Error: {error}')
        else:
            messages.error(request, f'❌ Error al crear respaldos. {error_count} errores encontrados')
            for error in errors[:3]:
                messages.error(request, f'Error: {error}')
        
    except Exception as e:
        messages.error(request, f'Error crítico al ejecutar respaldos: {str(e)}')
        print(f"Critical error in run_auto_backups_view: {str(e)}")
        print(traceback.format_exc())
    
    return redirect('settings')

@login_required
def about(request):
    """About page with version history"""
    versions = [
        {
            'version': '1.0.0',
            'date': '2025-12-31',
            'notes': [
                'Gestión completa de instancias Odoo (crear, desplegar, detener, reiniciar, eliminar)',
                'Orquestación de contenedores Docker con PostgreSQL 13',
                'Soporte multi-versión de Odoo (10.0 - 19.0)',
                'Integración con repositorios GitHub para módulos personalizados',
                'Sistema completo de backup y restauración',
                'Crear nuevas instancias desde backups existentes',
                'Logs en tiempo real y acceso a consola de contenedores',
                'Gestión de certificados SSL/TLS con Let\'s Encrypt',
                'Configuración de dominios personalizados',
                'Monitoreo de recursos y métricas de contenedores',
                'Autenticación de usuarios y gestión de perfiles',
                'Interfaz con pestañas para detalles de instancia',
                'Sistema de nomenclatura automática para instancias desde backup (name-copy-N)',
                'Detección automática de bases de datos',
                'Respaldo de filestore desde contenedores Docker',
            ]
        }
    ]
    
    return render(request, 'orchestrator/about.html', {
        'current_version': '1.0.0',
        'versions': versions
    })

@login_required
def generate_ssl_certificate(request):
    """Generate SSL certificate using Let's Encrypt"""
    from .config_models import GitHubConfig
    from .services import SSLService
    from django.contrib import messages
    
    if request.method == 'POST':
        config = GitHubConfig.objects.get(user=request.user)
        domain = request.POST.get('domain')
        email = request.POST.get('email')
        
        if not domain:
            messages.error(request, 'Debes proporcionar un dominio')
            return redirect('settings')
        
        if not email:
            messages.error(request, 'Debes proporcionar un email')
            return redirect('settings')
        
        # Generate certificate
        success, message, cert_path, key_path = SSLService.generate_certificate(domain, email)
        
        if success:
            # Update config with new paths
            config.main_domain = domain
            config.ssl_certificate_path = cert_path
            config.ssl_key_path = key_path
            config.ssl_enabled = True
            config.ssl_email = email
            config.save()
            
            # Update Traefik configuration for HTTPS
            from .traefik_service import TraefikService
            traefik_success, traefik_msg = TraefikService.generate_dynamic_config(
                domain=domain,
                ssl_enabled=True,
                cert_path=cert_path,
                key_path=key_path
            )
            
            messages.success(request, message)
            if traefik_success:
                messages.success(request, f'✅ {traefik_msg}. HTTPS configurado correctamente.')
            else:
                messages.warning(request, f'Certificado generado pero error en Traefik: {traefik_msg}')
        else:
            messages.error(request, message)
    
    return redirect('settings')

@login_required
def instance_backup(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    
    # Handle both GET and POST
    if request.method == 'POST':
        include_filestore = request.POST.get('filestore', 'true') == 'true'
        redirect_url = 'instance-detail'
    else:
        include_filestore = request.GET.get('filestore', 'true') == 'true'
        redirect_url = 'instance-backups'
    
    try:
        service = DockerService()
        backup_record = service.backup_instance(instance, include_filestore=include_filestore, user=request.user)
        
        from django.contrib import messages
        messages.success(request, f'Backup creado exitosamente: {backup_record.filename}')
    except Exception as e:
        from django.contrib import messages
        messages.error(request, f'Error creating backup: {str(e)}')
    
    # If coming from instance detail (POST), redirect to the backups tab
    if request.method == 'POST':
        from django.urls import reverse
        return redirect(reverse('instance-detail', kwargs={'pk': pk}) + '#backups')
    
    return redirect(redirect_url, pk=pk)

@login_required
def instance_restore(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    
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
    instance = get_object_or_404(Instance, pk=pk)
    from .backup_models import Backup
    backups = Backup.objects.filter(instance=instance)
    return render(request, 'orchestrator/instance_backups.html', {
        'instance': instance,
        'backups': backups
    })

@login_required
def backup_download(request, backup_id):
    from .backup_models import Backup
    backup = get_object_or_404(Backup, pk=backup_id)
    
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
    from .backup_models import Backup
    backup = get_object_or_404(Backup, pk=backup_id)
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
    from .backup_models import Backup
    backup = get_object_or_404(Backup, pk=backup_id)
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
    from .backup_models import Backup
    import zipfile
    import json
    
    backup = get_object_or_404(Backup, pk=backup_id)
    
    if request.method == 'POST':
        new_name = request.POST.get('name', '')
        
        if not new_name:
            from django.contrib import messages
            messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
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
            
            # Create new instance
            new_instance = Instance.objects.create(
                name=new_name,
                odoo_version=metadata.get('odoo_version', backup.instance.odoo_version),
                github_repo=metadata.get('github_repo', backup.instance.github_repo),
                github_branch=metadata.get('github_branch', backup.instance.github_branch),
                database_name=original_db_name,
                port=port,
                status='deploying',
                origin='backup'
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
                from .config_models import GitHubConfig
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
            from .email_notifications import send_instance_notification
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

# User Management Views
@login_required
def user_list(request):
    """List all users (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'orchestrator/user_list.html', {'users': users})

@login_required
def user_create(request):
    """Create a new user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        
        # Validation
        if not username or not password:
            messages.error(request, 'Usuario y contraseña son requeridos')
            return render(request, 'orchestrator/user_create.html')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, f'El usuario "{username}" ya existe')
            return render(request, 'orchestrator/user_create.html')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        user.is_superuser = is_superuser
        user.is_staff = is_staff
        user.save()
        
        messages.success(request, f'Usuario "{username}" creado exitosamente')
        return redirect('user-list')
    
    return render(request, 'orchestrator/user_create.html')

@login_required
def user_edit(request, user_id):
    """Edit user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    user_to_edit = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        is_active = request.POST.get('is_active') == 'on'
        new_password = request.POST.get('new_password')
        
        user_to_edit.email = email
        user_to_edit.is_superuser = is_superuser
        user_to_edit.is_staff = is_staff
        user_to_edit.is_active = is_active
        
        if new_password:
            user_to_edit.set_password(new_password)
        
        user_to_edit.save()
        
        messages.success(request, f'Usuario "{user_to_edit.username}" actualizado exitosamente')
        return redirect('user-list')
    
    return render(request, 'orchestrator/user_edit.html', {'user_to_edit': user_to_edit})

@login_required
def user_delete(request, user_id):
    """Delete user (admin only)"""
    from django.contrib.auth.models import User
    from django.contrib import messages
    
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permisos para acceder a esta página')
        return redirect('instance-list')
    
    user_to_delete = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        if user_to_delete == request.user:
            messages.error(request, 'No puedes eliminar tu propio usuario')
            return redirect('user-list')
        
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f'Usuario "{username}" eliminado exitosamente')
    
    return redirect('user-list')

# User Profile Views
@login_required
def user_profile(request):
    """View and edit current user's profile"""
    from django.contrib import messages
    from .models import UserProfile
    
    # Ensure profile exists
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update user info
        request.user.first_name = request.POST.get('first_name', '')
        request.user.last_name = request.POST.get('last_name', '')
        request.user.email = request.POST.get('email', '')
        request.user.save()
        
        # Update profile
        profile.bio = request.POST.get('bio', '')
        profile.phone = request.POST.get('phone', '')
        
        # Handle avatar upload
        if 'avatar' in request.FILES:
            profile.avatar = request.FILES['avatar']
        
        profile.save()
        
        messages.success(request, 'Perfil actualizado exitosamente')
        return redirect('user-profile')
    
    return render(request, 'orchestrator/user_profile.html', {'profile': profile})

@login_required
def user_change_password(request):
    """Change current user's password"""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib import messages
    
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # Validate current password
        if not request.user.check_password(current_password):
            messages.error(request, 'La contraseña actual es incorrecta')
            return redirect('user-profile')
        
        # Validate new passwords match
        if new_password != confirm_password:
            messages.error(request, 'Las contraseñas nuevas no coinciden')
            return redirect('user-profile')
        
        # Validate password strength
        if len(new_password) < 8:
            messages.error(request, 'La contraseña debe tener al menos 8 caracteres')
            return redirect('user-profile')
        
        # Change password
        request.user.set_password(new_password)
        request.user.save()
        
        # Keep user logged in
        update_session_auth_hash(request, request.user)
        
        messages.success(request, 'Contraseña cambiada exitosamente')
    
    return redirect('user-profile')
