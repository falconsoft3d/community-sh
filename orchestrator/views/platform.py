"""Platform administration: metrics, settings, panel SSL and manual backups."""
from ..models import Instance

from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from ..permissions import (
    superuser_required,
    validate_domain,
)


@login_required
@superuser_required
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
    from ..config_models import GitHubConfig
    from django.contrib import messages
    
    # Get or create GitHub config for the user
    config, created = GitHubConfig.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update configuration based on which fields are present in POST
        # This allows each tab to submit independently without affecting others
        
        # Update GitHub configuration if present
        if 'personal_access_token' in request.POST:
            config.personal_access_token = request.POST.get('personal_access_token', '')
            config.default_organization = request.POST.get('default_organization', '')
            config.webhook_secret = request.POST.get('webhook_secret', '')

        # The remaining sections are platform-wide: only superusers may change them
        if not request.user.is_superuser:
            config.save()
            messages.success(request, 'Settings saved successfully')
            return redirect('settings')

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
            config.main_domain = request.POST.get('main_domain', '').strip().lower()
            try:
                validate_domain(config.main_domain)
            except ValidationError:
                messages.error(request, 'Formato de dominio inválido')
                return redirect('settings')
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
            from ..traefik_service import TraefikService
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
@superuser_required
@require_POST
def run_auto_backups_view(request):
    """Execute automatic backups for all instances"""
    from django.contrib import messages
    from ..config_models import GitHubConfig
    from ..services import DockerService
    from ..backup_models import Backup
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
@superuser_required
def generate_ssl_certificate(request):
    """Generate SSL certificate using Let's Encrypt"""
    from ..config_models import GitHubConfig
    from ..services import SSLService
    from django.contrib import messages
    
    if request.method == 'POST':
        config = GitHubConfig.objects.get(user=request.user)
        domain = request.POST.get('domain')
        email = request.POST.get('email')
        
        if not domain:
            messages.error(request, 'Debes proporcionar un dominio')
            return redirect('settings')

        domain = domain.strip().lower()
        try:
            validate_domain(domain)
        except ValidationError:
            messages.error(request, 'Formato de dominio inválido')
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
            from ..traefik_service import TraefikService
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
