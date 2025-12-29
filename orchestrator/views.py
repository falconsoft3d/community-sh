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
    from .blog_models import BlogPost
    posts = BlogPost.objects.filter(published=True)
    return render(request, 'orchestrator/blog_list.html', {'posts': posts})

def blog_detail(request, slug):
    """Blog post detail page"""
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
        # Save the instance first
        response = super().form_valid(form)
        # Then trigger deployment
        service = DockerService()
        try:
            service.deploy_instance(self.object)
        except Exception as e:
            print(f"Error deploying instance: {e}")
        return response

class InstanceDetailView(LoginRequiredMixin, DetailView):
    model = Instance

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = DockerService()
        context['logs'] = service.get_logs(self.object)
        return context

@login_required
def instance_deploy(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    if request.method == 'POST':
        service = DockerService()
        try:
            service.deploy_instance(instance)
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
        instance.save()
        
        messages.success(request, f'Dominio {domain} configurado correctamente')
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
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    
    memory = psutil.virtual_memory()
    memory_percent = memory.percent
    memory_used_gb = round(memory.used / (1024**3), 2)
    memory_total_gb = round(memory.total / (1024**3), 2)
    
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
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
        }
    }
    
    return render(request, 'orchestrator/metrics.html', context)

@login_required
def settings_view(request):
    from .config_models import GitHubConfig
    from django.contrib import messages
    
    # Get or create GitHub config for the user
    config, created = GitHubConfig.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update configuration
        config.personal_access_token = request.POST.get('personal_access_token', '')
        config.default_organization = request.POST.get('default_organization', '')
        config.webhook_secret = request.POST.get('webhook_secret', '')
        config.registration_enabled = request.POST.get('registration_enabled') == 'on'
        
        # Update domain and SSL configuration
        config.main_domain = request.POST.get('main_domain', '')
        config.ssl_enabled = request.POST.get('ssl_enabled') == 'on'
        config.ssl_certificate_path = request.POST.get('ssl_certificate_path', '')
        config.ssl_key_path = request.POST.get('ssl_key_path', '')
        
        config.save()
        
        messages.success(request, 'Configuración guardada exitosamente')
        return redirect('settings')
    
    return render(request, 'orchestrator/settings.html', {'config': config})

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
        cert_path, key_path, success, message = SSLService.generate_certificate(domain, email)
        
        if success:
            # Update config with new paths
            config.main_domain = domain
            config.ssl_certificate_path = cert_path
            config.ssl_key_path = key_path
            config.ssl_enabled = True
            config.save()
            messages.success(request, message)
        else:
            messages.error(request, message)
    
    return redirect('settings')

@login_required
def instance_backup(request, pk):
    instance = get_object_or_404(Instance, pk=pk)
    include_filestore = request.GET.get('filestore', 'true') == 'true'
    
    try:
        service = DockerService()
        backup_record = service.backup_instance(instance, include_filestore=include_filestore, user=request.user)
        
        from django.contrib import messages
        messages.success(request, f'Backup creado exitosamente: {backup_record.filename}')
    except Exception as e:
        from django.contrib import messages
        messages.error(request, f'Error creating backup: {str(e)}')
    
    return redirect('instance-backups', pk=pk)

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
