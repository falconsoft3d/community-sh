"""GitHub webhooks: a push to a repository updates every instance that uses it (Modules → automatic update)."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import Instance, generate_webhook_secret
from ..permissions import get_instance_for_user
from ..services import webhooks


def hook_url(instance):
    """The public address GitHub calls (the platform domain when there is one)."""
    from ..services.trials import public_url
    return public_url(reverse('github-webhook', args=[instance.pk]))


@csrf_exempt
@require_POST
def github_webhook(request, pk):
    """Called by GitHub on every push (signed with the instance's webhook secret)."""
    instance = Instance.objects.filter(pk=pk).first()
    # Same answer for an unknown instance and a bad signature: nothing to probe
    if instance is None or not webhooks.signature_ok(instance, request.body, request.headers.get('X-Hub-Signature-256')):
        return JsonResponse({'detail': 'Firma no válida'}, status=403)
    delivery = request.headers.get('X-GitHub-Delivery', '')
    if delivery and not cache.add(f'github-delivery:{delivery}', 1, 24 * 3600):
        return JsonResponse({'detail': 'Entrega repetida: ignorada'}, status=200)
    event = request.headers.get('X-GitHub-Event', '')
    if event == 'ping':
        return JsonResponse({'detail': 'pong'})
    if event != 'push':
        return JsonResponse({'detail': f'Evento «{event}» ignorado: solo se atiende push'}, status=202)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({'detail': 'JSON no válido (configura el webhook con Content type: application/json)'}, status=400)
    status, message = webhooks.handle_push(instance, payload)
    return JsonResponse({'detail': message}, status=status)


def _modules(pk):
    return redirect(reverse('instance-detail', args=[pk]) + '#modules')


@login_required
@require_POST
def instance_auto_update(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    mode = request.POST.get('auto_update', '')
    if mode not in Instance.AutoUpdate.values:
        messages.error(request, 'Modo de actualización no válido')
        return _modules(pk)
    instance.auto_update = mode
    instance.save(update_fields=['auto_update'])
    if mode:
        messages.success(request, f'Actualización automática: {instance.get_auto_update_display()}. Se actualiza cada noche; '
                                  'para hacerlo al momento con cada push hace falta un webhook en el repositorio (el de esta '
                                  'u otra instancia): pulsa «Crear webhook en GitHub» o añádelo a mano.')
    else:
        messages.success(request, 'Actualización automática desactivada')
    return _modules(pk)


@login_required
@require_POST
def instance_webhook_github(request, pk):
    """Create or refresh the webhook on every GitHub repository of the instance (owner's token)."""
    instance = get_instance_for_user(request.user, pk, manage=True)
    results = webhooks.create_github_hooks(instance, hook_url(instance))
    if not results:
        messages.error(request, 'La instancia no tiene repositorios de GitHub')
    for name, ok, message in results:
        (messages.success if ok else messages.error)(request, f'{name}: {message}')
    return _modules(pk)


@login_required
@require_POST
def instance_webhook_secret(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    instance.webhook_secret = generate_webhook_secret()
    instance.save(update_fields=['webhook_secret'])
    messages.warning(request, 'Secreto nuevo: los webhooks con el anterior dejan de funcionar. '
                              'Pulsa «Crear webhook en GitHub» para actualizarlos.')
    return _modules(pk)
