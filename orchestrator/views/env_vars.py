"""Environment variables of an instance (Modules tab): saved, and applied by a redeploy."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..instance_env import parse_env
from ..task_models import Task
from ..permissions import get_instance_for_user
from ..tasks import enqueue


@login_required
@require_POST
def instance_env_vars(request, pk):
    instance = get_instance_for_user(request.user, pk, manage=True)
    text = request.POST.get('env_vars', '').replace('\r\n', '\n').strip()
    try:
        variables = parse_env(text)
    except ValueError as error:
        messages.error(request, f'Variables de entorno no guardadas: {error}')
        return redirect(reverse('instance-detail', args=[pk]) + '#modules')
    instance.env_vars = text
    instance.save(update_fields=['env_vars', 'updated_at'])
    names = ', '.join(sorted(variables)) or 'ninguna'
    if request.POST.get('redeploy'):
        enqueue(Task.Kind.DEPLOY, instance, request.user)
        messages.success(request, f'Variables de entorno guardadas ({names}). Redesplegando la instancia para aplicarlas.')
    else:
        messages.success(request, f'Variables de entorno guardadas ({names}). Se aplican en el próximo despliegue.')
    return redirect(reverse('instance-detail', args=[pk]) + '#modules')
