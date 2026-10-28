"""Odoo instance management."""
import re

from ..models import Instance
from ..services import DockerService

from django.views.generic import ListView, CreateView, DetailView
from django.urls import reverse_lazy
from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_POST
from ..ai_models import AIAttachment
from ..task_models import Task
from ..tasks import enqueue
from ..permissions import (
    can_manage,
    domain_in_use,
    get_instance_for_user,
    is_client,
    instances_for,
    projects_for,
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
    paginate_by = 20

    def get_queryset(self):
        queryset = instances_for(self.request.user).select_related('project').order_by(*self.ordering)
        if self.request.GET.get('project'):
            queryset = queryset.filter(project_id=self.request.GET['project'])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = projects_for(self.request.user)
        context['selected_project'] = self.request.GET.get('project', '')
        if context.get('page_obj'):
            from ..pagination import with_links
            with_links(self.request, context['page_obj'])
        return context


class InstanceCreateView(LoginRequiredMixin, CreateView):
    model = Instance
    from ..forms import InstanceForm
    form_class = InstanceForm
    
    def dispatch(self, request, *args, **kwargs):
        if is_client(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_initial(self):
        # "Nueva instancia" from a project page preselects that project
        initial = super().get_initial()
        if self.request.GET.get('project'):
            initial['project'] = self.request.GET['project']
        return initial
    
    def get_success_url(self):
        return reverse_lazy('instance-detail', args=[self.object.pk])
    
    def form_valid(self, form):
        form.instance.origin = 'manual'
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        
        # The worker creates the instance's GitHub branch, deploys it and notifies
        enqueue(Task.Kind.DEPLOY, self.object, self.request.user, create_branch=True, notify=True)
        messages.info(self.request, 'Instancia creada. El despliegue está en cola y puede tardar unos minutos.')
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
        context['can_manage'] = can_manage(self.request.user, self.object)
        from ..services.ai import get_ai_config
        context['ai_enabled'] = context['can_manage'] and get_ai_config() is not None
        context['tasks'] = list(self.object.tasks.all()[:5])
        from ..services.odoo_migration import MIN_TARGET_VERSION, STEP_LABELS, STEPS
        context['migration_steps'] = [(step, STEP_LABELS[step]) for step in STEPS]
        context['migration_supported'] = int(float(self.object.odoo_version)) >= MIN_TARGET_VERSION
        context['migration_min_version'] = MIN_TARGET_VERSION
        context['last_migration'] = self.object.tasks.filter(kind=Task.Kind.ODOO_MIGRATION).first()
        context['has_active_tasks'] = any(task.is_active for task in context['tasks'])
        
        return context


@login_required
@require_POST
def instance_deploy(request, pk):
    instance = get_instance_for_user(request.user, pk)
    enqueue(Task.Kind.DEPLOY, instance, request.user)
    messages.info(request, 'Despliegue en cola')
    return HttpResponseRedirect(reverse_lazy('instance-detail', args=[pk]))


@login_required
def instance_tasks_api(request, pk):
    """Recent tasks of an instance, polled by the detail page while any is active."""
    instance = get_instance_for_user(request.user, pk)
    tasks = [
        {
            'id': task.id,
            'kind': task.get_kind_display(),
            'status': task.status,
            'status_display': task.get_status_display(),
            'result': task.result,
            'created_at': task.created_at.isoformat(),
        }
        for task in instance.tasks.all()[:5]
    ]
    return JsonResponse({
        'status': instance.status,
        'active': any(t['status'] in (Task.Status.PENDING, Task.Status.RUNNING) for t in tasks),
        'tasks': tasks,
    })


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
    instance = get_instance_for_user(request.user, pk, manage=True)
    
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
    instance = get_instance_for_user(request.user, pk, manage=True)
    
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
    instance = get_instance_for_user(request.user, pk, manage=True)
    
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
    instance = get_instance_for_user(request.user, pk, manage=True)
    
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
@require_POST
def instance_update_name(request, pk):
    """Rename an instance (its containers, network and workspace are moved by the worker)"""
    instance = get_instance_for_user(request.user, pk, manage=True)
    new_name = request.POST.get('name', '').strip().lower()
    
    if not new_name:
        messages.error(request, 'El nombre no puede estar vacío')
        return redirect('instance-detail', pk=pk)
    
    try:
        validate_resource_name(new_name)
    except ValidationError as e:
        messages.error(request, e.messages[0])
        return redirect('instance-detail', pk=pk)
    
    if new_name == instance.name:
        return redirect('instance-detail', pk=pk)
    
    if Instance.objects.filter(name=new_name).exclude(pk=pk).exists():
        messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
        return redirect('instance-detail', pk=pk)
    
    enqueue(Task.Kind.RENAME, instance, request.user, new_name=new_name)
    messages.info(request, f'Renombrado a "{new_name}" en cola')
    return redirect('instance-detail', pk=pk)


@login_required
@require_POST
def instance_install_module(request, pk):
    """Upload a module ZIP: the worker adds it to the GitHub repo and redeploys"""
    instance = get_instance_for_user(request.user, pk, manage=True)
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
    
    # Keep the upload where the worker can read it; the task deletes it afterwards
    import os
    import uuid
    from django.conf import settings
    uploads_dir = os.path.join(settings.BASE_DIR, 'backups', 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, f'{uuid.uuid4().hex}.zip')
    with open(file_path, 'wb') as f:
        for chunk in module_file.chunks():
            f.write(chunk)
    
    enqueue(Task.Kind.INSTALL_MODULE, instance, request.user, file_path=file_path, label=module_file.name)
    messages.info(request, 'Instalación del módulo en cola. Se agregará al repositorio y se redesplegará.')
    return redirect('instance-detail', pk=pk)


@login_required
def instance_delete(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    if request.method == 'POST':
        from ..tasks import destroy_instance
        destroy_instance(instance, request.user)
        return redirect('instance-list')
    return redirect('instance-detail', pk=pk)


@login_required
def instance_duplicate(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    
    if request.method != 'POST':
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    new_name = request.POST.get('new_name', '').strip().lower()
    
    if not new_name:
        messages.error(request, 'Debes proporcionar un nombre para la nueva instancia')
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    try:
        validate_resource_name(new_name)
    except ValidationError as e:
        messages.error(request, e.messages[0])
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    if Instance.objects.filter(name=new_name).exists():
        messages.error(request, f'Ya existe una instancia con el nombre "{new_name}"')
        return render(request, 'orchestrator/instance_duplicate.html', {'instance': instance})
    
    enqueue(Task.Kind.DUPLICATE, instance, request.user, new_name=new_name)
    messages.info(request, f'Duplicación como "{new_name}" en cola. La nueva instancia aparecerá en la lista al terminar.')
    return redirect('instance-detail', pk=pk)


def _ai_message_json(message):
    tools = []
    for call in message.tool_calls or []:
        try:
            import json
            arguments = json.loads(call['function'].get('arguments') or '{}')
        except ValueError:
            arguments = {}
        if call['function']['name'] == 'update_plan':
            continue  # shown as the plan card of the turn
        tools.append({'name': call['function']['name'], 'target': arguments.get('path') or arguments.get('module') or ''})
    content = message.content
    if message.role == 'user':
        # The tagged-modules context is for the model, not for the chat bubble
        content = content.split('\n\n[Módulos etiquetados]')[0]
    data = {'id': message.id, 'role': message.role, 'content': content, 'tools': tools,
            'created_at': message.created_at.isoformat()}
    if message.role == 'user':
        data['attachments'] = [{'name': a.name, 'size': a.size, 'type': a.content_type} for a in message.attachments.all()]
        data['plan'] = message.plan or []
    return data


def _ai_messages_json(instance, messages_list):
    """Serialize messages; the last assistant message of each turn carries its undo info."""
    from django.db.models import Count, Q
    from ..ai_models import AIFileChange
    turns = {row['turn_id']: row for row in AIFileChange.objects.filter(turn__instance=instance)
             .values('turn_id').annotate(files=Count('id'), pending=Count('id', filter=Q(reverted_at__isnull=True)))}
    last_of_turn = {}
    for message in messages_list:
        if message.role == 'assistant' and message.turn_id:
            last_of_turn[message.turn_id] = message.id
    data = []
    for message in messages_list:
        item = _ai_message_json(message)
        info = turns.get(message.turn_id)
        if info and last_of_turn.get(message.turn_id) == message.id:
            item['undo'] = {'turn': message.turn_id, 'files': info['files'], 'reverted': info['pending'] == 0}
        if message.role == 'assistant' and not (item['content'] or item['tools'] or item.get('undo')):
            continue  # only updated the plan
        data.append(item)
    return data


@login_required
@require_POST
def instance_ai_revert(request, pk, turn_id):
    """Undo the file changes of a turn (and of every later turn)."""
    from ..ai_models import AIMessage
    from ..services.ai_assistant import revert_turns
    instance = get_instance_for_user(request.user, pk, manage=True)
    turn = instance.ai_messages.filter(pk=turn_id, role=AIMessage.Role.USER).first()
    if turn is None:
        return JsonResponse({'error': 'Petición no encontrada'}, status=404)
    summary = revert_turns(instance, request.user, turn)
    return JsonResponse({'summary': summary, 'messages': _ai_messages_json(instance, list(instance.ai_messages.exclude(role='tool')))})


AI_MAX_FILES = 5
AI_MAX_FILE_BYTES = 20 * 1024 * 1024


def _ai_running_task(instance):
    return instance.tasks.filter(kind=Task.Kind.AI_CHAT, status__in=[Task.Status.PENDING, Task.Status.RUNNING]).first()


def _ai_conversation(instance):
    task = _ai_running_task(instance)
    messages_list = list(instance.ai_messages.exclude(role='tool').prefetch_related('attachments'))
    return {'messages': _ai_messages_json(instance, messages_list), 'running': task is not None,
            'turn': task.params.get('turn') if task else None}


@login_required
def instance_ai_chat(request, pk):
    """
    GET: the conversation and whether a request is still running. POST (JSON or multipart with
    files): store the message and queue it for the AI worker, which runs the tools step by step.
    """
    import json
    from ..services.ai import get_ai_config
    from ..services.ai_assistant import attachment_type, start_turn
    instance = get_instance_for_user(request.user, pk, manage=True)
    if get_ai_config() is None:
        return JsonResponse({'error': 'El asistente de IA no está configurado (Settings → IA)'}, status=400)
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                payload = json.loads(request.body or '{}')
            except ValueError:
                payload = {}
            modules = payload.get('modules') or []
        else:
            payload = request.POST
            try:
                modules = json.loads(payload.get('modules') or '[]')
            except ValueError:
                modules = []
        text = str(payload.get('message', '')).strip()
        modules = [str(m) for m in modules][:10]
        files = request.FILES.getlist('files')
        if not text and not files:
            return JsonResponse({'error': 'Escribe un mensaje'}, status=400)
        if len(files) > AI_MAX_FILES:
            return JsonResponse({'error': f'Adjunta como máximo {AI_MAX_FILES} archivos'}, status=400)
        for upload in files:
            if attachment_type(upload.name) is None:
                return JsonResponse({'error': f'Tipo de archivo no admitido: {upload.name} (PDF, imágenes o texto)'}, status=400)
            if upload.size > AI_MAX_FILE_BYTES:
                return JsonResponse({'error': f'{upload.name} supera los 20 MB'}, status=400)
        if _ai_running_task(instance):
            return JsonResponse({'error': 'La IA todavía está trabajando en la petición anterior'}, status=409)
        turn = start_turn(instance, request.user, text or 'Revisa los archivos adjuntos.', modules, files)
        enqueue(Task.Kind.AI_CHAT, instance, request.user, turn=turn.pk)
        return JsonResponse(_ai_conversation(instance))
    return JsonResponse(_ai_conversation(instance))


@login_required
@require_POST
def instance_ai_stop(request, pk):
    """Ask the running request to stop after its current step."""
    from django.core.cache import cache
    from ..services.ai_assistant import stop_key
    instance = get_instance_for_user(request.user, pk, manage=True)
    task = _ai_running_task(instance)
    if task is None:
        return JsonResponse({'error': 'No hay ninguna petición en curso'}, status=400)
    if task.status == Task.Status.PENDING:
        task.status, task.result = Task.Status.FAILED, 'Cancelada antes de empezar'
        task.save(update_fields=['status', 'result'])
    else:
        cache.set(stop_key(task.params['turn']), True, 3600)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def instance_ai_reset(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    if _ai_running_task(instance):
        return JsonResponse({'error': 'Espera a que la IA termine o detenla antes de borrar la conversación'}, status=409)
    for attachment in AIAttachment.objects.filter(message__instance=instance):
        attachment.file.delete(save=False)
    instance.ai_messages.all().delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def instance_repo_add(request, pk):
    from ..repository_models import REPO_URL_RE
    instance = get_instance_for_user(request.user, pk, manage=True)
    url = request.POST.get('url', '').strip()
    branch = request.POST.get('branch', '').strip() or 'main'
    if not REPO_URL_RE.match(url):
        messages.error(request, 'URL inválida: usa la URL HTTPS de clonado (p. ej. https://github.com/OCA/web.git)')
    elif not re.match(r'^[A-Za-z0-9._/-]+$', branch):
        messages.error(request, 'Rama inválida')
    elif instance.repositories.filter(url=url).exists() or url == instance.github_repo:
        messages.error(request, 'Ese repositorio ya está en la instancia')
    else:
        repository = instance.repositories.create(url=url, branch=branch)
        messages.success(request, f'Repositorio {repository.slug} añadido. Despliega la instancia para aplicarlo.')
    from django.urls import reverse
    return redirect(reverse('instance-detail', args=[pk]) + '#modules')


@login_required
@require_POST
def instance_repo_remove(request, pk, repo_id):
    instance = get_instance_for_user(request.user, pk, manage=True)
    repository = instance.repositories.filter(pk=repo_id).first()
    if repository:
        repository.delete()
        messages.success(request, f'Repositorio {repository.slug} quitado. Despliega la instancia para aplicarlo.')
    from django.urls import reverse
    return redirect(reverse('instance-detail', args=[pk]) + '#modules')



@login_required
def instance_ai_modules(request, pk):
    """Custom modules of the instance, for @mentions in the AI chat."""
    from ..services.ai_assistant import find_custom_modules
    instance = get_instance_for_user(request.user, pk, manage=True)
    return JsonResponse({'modules': find_custom_modules(instance)})


@login_required
@require_POST
def instance_admin_login(request, pk):
    """Open Odoo as its administrator through a signed, one-time, 60-second link."""
    import hashlib
    import hmac
    import secrets
    import time
    from urllib.parse import urlencode
    from ..services.docker_service import admin_login_secret
    instance = get_instance_for_user(request.user, pk, manage=True)
    database = instance.database_name
    if not database:
        try:
            service = DockerService()
            databases = service._list_user_databases(service.client.containers.get(f'db_{instance.name}'))
        except Exception:
            databases = []
        if not databases:
            messages.error(request, 'La instancia todavía no tiene base de datos: créala primero desde Odoo')
            return redirect('instance-detail', pk=pk)
        database = databases[0]
    expires, nonce = str(int(time.time()) + 60), secrets.token_urlsafe(16)
    signature = hmac.new(admin_login_secret(instance).encode(), f'{database}:{expires}:{nonce}'.encode(), hashlib.sha256).hexdigest()
    query = urlencode({'db': database, 'exp': expires, 'nonce': nonce, 'sig': signature})
    return HttpResponseRedirect(f'{instance.url.rstrip("/")}/community_sh/login?{query}')
