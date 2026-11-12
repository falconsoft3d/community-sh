"""Platform administration: metrics, settings, panel SSL and manual backups."""
from ..api_docs import API_ENDPOINTS
from ..models import Instance
from ..task_models import Task
from ..tasks import enqueue

from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from ..permissions import (
    superuser_required,
    validate_domain,
)
from ..reauth import recent_auth_required


@login_required
@superuser_required
def metrics_view(request):
    from ..services.metrics import collect_metrics
    return render(request, 'orchestrator/metrics.html', {'metrics': collect_metrics()})


@login_required
@superuser_required
def metrics_data(request):
    """Polled by the Metrics page; container stats only while that tab is open (they are slow)."""
    from django.http import JsonResponse
    from ..services.metrics import collect_metrics
    return JsonResponse(collect_metrics(include_containers=request.GET.get('containers') == '1'))


@login_required
@superuser_required
def metrics_disk(request):
    """Disk of every instance (volumes, code, backups), measured at most every 10 minutes (?refresh=1 now)."""
    from django.http import JsonResponse
    from ..services.metrics import instance_disk_usage
    try:
        return JsonResponse(instance_disk_usage(refresh=request.GET.get('refresh') == '1'))
    except Exception as e:
        return JsonResponse({'rows': [], 'error': str(e)}, status=503)


@login_required
@recent_auth_required
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

        from ..audit import record
        record(request, 'settings', request.POST.get('section') or 'github')
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
        if request.POST.get('section') == 'backups':
            _read_offsite_fields(request, config)
        if request.POST.get('section') == 'general':
            config.alerts_enabled = 'alerts_enabled' in request.POST
            webhook = request.POST.get('alert_webhook_url', '').strip()
            if webhook and not webhook.startswith(('https://', 'http://')):
                messages.error(request, 'El webhook de alertas debe ser una URL http(s)')
            else:
                config.alert_webhook_url = webhook
        
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
        
        if section == 'mcp':
            config.mcp_enabled = 'mcp_enabled' in request.POST
        
        if section == 'ia':
            config.ai_enabled = 'ai_enabled' in request.POST
            config.openai_model = request.POST.get('openai_model', '').strip()
            config.ai_instructions = request.POST.get('ai_instructions', '').strip()
            # Empty field keeps the stored key; the checkbox removes it
            new_key = request.POST.get('openai_api_key', '').strip()
            if new_key:
                config.openai_api_key = new_key
            elif 'remove_openai_api_key' in request.POST:
                config.openai_api_key = ''
        
        if section == 'email':
            config.smtp_enabled = 'smtp_enabled' in request.POST
            config.smtp_host = request.POST.get('smtp_host', '').strip()
            config.smtp_security = request.POST.get('smtp_security', 'starttls')
            if config.smtp_security not in ('starttls', 'ssl', 'none'):
                config.smtp_security = 'starttls'
            config.smtp_username = request.POST.get('smtp_username', '').strip()
            config.smtp_from_email = request.POST.get('smtp_from_email', '').strip()
            config.smtp_from_name = request.POST.get('smtp_from_name', '').strip()
            try:
                config.smtp_port = int(request.POST.get('smtp_port') or 587)
                from django.core.validators import validate_email
                if config.smtp_from_email:
                    validate_email(config.smtp_from_email)
            except (ValueError, ValidationError):
                messages.error(request, 'Revisa el puerto y el remitente del correo')
                return redirect(reverse('settings') + '#email')
            # Empty field keeps the stored password; the checkbox removes it
            new_password = request.POST.get('smtp_password', '')
            if new_password:
                config.smtp_password = new_password
            elif 'remove_smtp_password' in request.POST:
                config.smtp_password = ''
            if config.smtp_enabled and not (config.smtp_host and config.smtp_from_email):
                messages.warning(request, 'Para enviar correos faltan el servidor y el remitente')

        if section == 'demos':
            try:
                config.trial_max_per_day = max(0, min(int(request.POST.get('trial_max_per_day', 10)), 1000))
                config.trial_max_active_total = max(0, min(int(request.POST.get('trial_max_active_total', 4)), 100))
            except ValueError:
                messages.error(request, 'Los límites de demos deben ser números')
                return redirect(reverse('settings') + '#demos')

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
            # The instances' subdomains hang off the main domain: rewrite every route
            result, *problems = TraefikService.configure_all()
            messages.info(request, result)
            for problem in problems:
                messages.warning(request, f'Configuración guardada, pero hubo un problema con Traefik: {problem}')
        
        messages.success(request, 'Settings saved successfully')
        return redirect('settings')
    
    from ..mcp_models import MCPToken
    from ..permissions import get_global_config
    global_config = get_global_config()
    new_token = request.session.pop('new_personal_token', None)
    return render(request, 'orchestrator/settings.html', {
        'new_token': new_token,
        'example_token': new_token['token'] if new_token else 'TU_TOKEN',
        'config': config,
        'mcp_enabled': bool(global_config and global_config.mcp_enabled),
        'mcp_tokens': MCPToken.objects.filter(user=request.user),
        'mcp_url': request.build_absolute_uri(reverse('mcp')),
        'api_url': request.build_absolute_uri('/api/'),
        'api_endpoints': API_ENDPOINTS,
    })


def _read_offsite_fields(request, config):
    """The S3 fields of Settings → Respaldos (an empty secret keeps the stored one)."""
    config.offsite_enabled = 'offsite_enabled' in request.POST
    for field in ('s3_endpoint_url', 's3_region', 's3_bucket', 's3_access_key', 's3_prefix'):
        setattr(config, field, request.POST.get(field, '').strip())
    if request.POST.get('s3_secret_key', '').strip():
        config.s3_secret_key = request.POST['s3_secret_key'].strip()
    try:
        config.offsite_retention_days = max(int(request.POST.get('offsite_retention_days') or 0), 0)
    except ValueError:
        pass


@login_required
@superuser_required
@require_POST
def backups_verify_now(request):
    """Settings → Respaldos → Comprobar backups ahora."""
    from django.contrib import messages
    from ..audit import record
    task = enqueue(Task.Kind.BACKUP_VERIFY, user=request.user)
    record(request, 'backups_verify')
    messages.info(request, f'Comprobación de backups en cola (tarea #{task.pk}); el resultado estará en Actividad')
    return redirect(reverse('settings') + '#backups')


@login_required
@superuser_required
@require_POST
def offsite_test(request):
    """Settings → Respaldos → Probar conexión: with what the form says now (not saved yet)."""
    from django.contrib import messages
    from ..config_models import GitHubConfig
    from ..services import offsite
    config = GitHubConfig.objects.filter(user=request.user).first() or GitHubConfig(user=request.user)
    _read_offsite_fields(request, config)
    if not config.s3_bucket or not config.s3_access_key or not config.s3_secret_key:
        messages.error(request, 'Rellena el bucket, la access key y la secret key')
    else:
        ok, message = offsite.test_connection(config)
        (messages.success if ok else messages.error)(request, message)
    return redirect(reverse('settings') + '#backups')


@login_required
@superuser_required
@require_POST
def run_auto_backups_view(request):
    """Queue a backup of every instance (with the configured retention)"""
    from django.contrib import messages
    from ..config_models import GitHubConfig
    
    config = GitHubConfig.objects.filter(user=request.user).first()
    retention = config.auto_backup_retention if config and config.auto_backup_retention else 5
    enqueue(Task.Kind.BACKUP_ALL, user=request.user, retention=retention)
    messages.info(request, 'Respaldo de todas las instancias en cola. El resultado aparecerá en Admin → Tasks.')
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


@login_required
@superuser_required
@require_POST
def settings_email_test(request):
    """Send a test email with the server typed in the form (an empty password uses the stored one)."""
    from django.core.validators import validate_email
    from django.http import JsonResponse
    from ..config_models import GitHubConfig
    from ..services import mail

    config = GitHubConfig.objects.filter(user=request.user).first()
    to = request.POST.get('to', '').strip() or request.user.email
    sender_email = request.POST.get('smtp_from_email', '').strip()
    try:
        validate_email(to)
        validate_email(sender_email)
        port = int(request.POST.get('smtp_port') or 587)
    except (ValidationError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Indica un remitente, un destinatario válido y el puerto'}, status=400)
    host = request.POST.get('smtp_host', '').strip()
    if not host:
        return JsonResponse({'ok': False, 'error': 'Indica el servidor SMTP'}, status=400)
    password = request.POST.get('smtp_password', '') or (config.smtp_password if config else '')
    name = request.POST.get('smtp_from_name', '').strip()
    try:
        from django.core.mail import EmailMessage
        EmailMessage('Prueba de correo de Community SH',
                     'Si lees esto, el servidor de correo saliente de Community SH funciona.',
                     f'{name} <{sender_email}>' if name else sender_email, [to],
                     connection=mail.connection(host, port, request.POST.get('smtp_security', 'starttls'),
                                                request.POST.get('smtp_username', '').strip(), password)).send()
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'No se pudo enviar: {e}'}, status=400)
    return JsonResponse({'ok': True, 'message': f'Correo de prueba enviado a {to}'})


@login_required
@superuser_required
@require_POST
def settings_ai_test(request):
    """Check the OpenAI key (typed or stored) and return the chat models it can use."""
    from django.http import JsonResponse
    from ..config_models import GitHubConfig
    from ..services.ai import AIError, list_chat_models

    config = GitHubConfig.objects.filter(user=request.user).first()
    api_key = request.POST.get('openai_api_key', '').strip() or (config.openai_api_key if config else '')
    if not api_key:
        return JsonResponse({'ok': False, 'error': 'Introduce una API key de OpenAI'}, status=400)
    try:
        models = list_chat_models(api_key)
    except AIError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    return JsonResponse({'ok': True, 'models': models})


@login_required
@superuser_required
def metrics_history_data(request):
    from django.http import JsonResponse
    from ..services.metrics import RANGES, metrics_history
    range_key = request.GET.get('range', '24h')
    if range_key not in RANGES:
        range_key = '24h'
    return JsonResponse({'range': range_key, 'points': metrics_history(range_key)})
