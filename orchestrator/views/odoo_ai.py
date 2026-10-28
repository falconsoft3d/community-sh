"""Requests written as "/ia ..." in an Odoo chatter (community_sh_ai module), signed with the instance secret."""
import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import Instance
from ..task_models import Task


@csrf_exempt
@require_POST
def odoo_ai_request(request, name):
    from ..services.ai import get_ai_config
    from ..services.ai_assistant import start_turn
    from ..services.odoo_bridge import verify
    from ..tasks import enqueue
    instance = get_object_or_404(Instance, name=name)
    if not verify(instance, request.body, request.headers.get('X-CSH-Timestamp'), request.headers.get('X-CSH-Signature')):
        return JsonResponse({'message': 'Firma no válida'}, status=403)
    data = json.loads(request.body)
    if get_ai_config() is None:
        return JsonResponse({'message': 'El asistente de IA no está configurado en Community SH (Settings → IA).'})
    if instance.tasks.filter(kind=Task.Kind.AI_CHAT, status__in=[Task.Status.PENDING, Task.Status.RUNNING]).exists():
        return JsonResponse({'message': 'La IA está trabajando en otra petición de esta instancia. Vuelve a pedirlo cuando termine.'})

    # The Odoo user isn't a panel user: the request runs as the instance owner
    user = instance.owner or (instance.project.owner if instance.project else None) or \
        User.objects.filter(is_superuser=True).order_by('id').first()
    text = (f"{data['text']}\n\n[Contexto Odoo]\nPetición escrita en el chatter de {data['model']} #{data['res_id']} "
            f"(«{data.get('record', '')}») por el usuario {data.get('login', '')} de la base de datos {data['db']}. "
            "«Esta lista», «este formulario» o «aquí» se refieren a las vistas de ese modelo: consúltalas con "
            "odoo_model_info. Tu respuesta final se publicará en ese chatter.")
    turn = start_turn(instance, user, text)
    enqueue(Task.Kind.AI_CHAT, instance, user, turn=turn.pk,
            odoo={'db': data['db'], 'model': data['model'], 'res_id': data['res_id']})
    return JsonResponse({'message': 'Recibido: trabajo en ello y te respondo aquí cuando termine. '
                                    'Puedes seguir el progreso en Community SH → la instancia → IA.'}, status=202)


@login_required
@require_POST
def instance_migrate(request, pk):
    """Queue a copy of data from another Odoo into this instance (passwords only travel in the cache)."""
    import secrets
    from django.contrib import messages
    from django.core.cache import cache
    from django.shortcuts import redirect
    from ..permissions import get_instance_for_user
    from ..services.odoo_migration import MIN_TARGET_VERSION, STEPS
    from ..tasks import enqueue
    instance = get_instance_for_user(request.user, pk, manage=True)
    back = redirect(f"{reverse('instance-detail', args=[pk])}#migrate")
    if int(float(instance.odoo_version)) < MIN_TARGET_VERSION:
        messages.error(request, f'La migración necesita que esta instancia sea Odoo {MIN_TARGET_VERSION} o posterior')
        return back
    form = {key: request.POST.get(key, '').strip() for key in (
        'source_url', 'source_db', 'source_login', 'source_password', 'target_db', 'target_login', 'target_password')}
    form['source_password'], form['target_password'] = request.POST.get('source_password', ''), request.POST.get('target_password', '')
    steps = [step for step in STEPS if step in request.POST.getlist('steps')]
    missing = [key for key, value in form.items() if not value]
    if missing or not steps:
        messages.error(request, 'Completa el origen, el destino y al menos un tipo de dato a migrar')
        return back
    if not form['source_url'].startswith(('http://', 'https://')):
        form['source_url'] = 'https://' + form['source_url']
    if instance.tasks.filter(kind=Task.Kind.ODOO_MIGRATION, status__in=[Task.Status.PENDING, Task.Status.RUNNING]).exists():
        messages.error(request, 'Ya hay una migración en curso para esta instancia')
        return back
    key = f'migration-credentials-{secrets.token_urlsafe(16)}'
    cache.set(key, form, 24 * 3600)
    enqueue(Task.Kind.ODOO_MIGRATION, instance, request.user, credentials=key, steps=steps,
            source=f"{form['source_url']} / {form['source_db']}")
    messages.success(request, 'Migración en cola: sigue el progreso en «Tareas recientes». Puedes repetirla: lo ya copiado no se duplica.')
    return back
