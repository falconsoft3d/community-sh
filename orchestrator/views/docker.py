"""Docker administration (superusers): containers, images, volumes and networks."""
import re

import docker
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.template.defaultfilters import filesizeformat
from django.views.decorators.http import require_POST

from ..permissions import superuser_required
from ..services import docker_admin
from ..task_models import Task
from ..tasks import enqueue

IMAGE_REFERENCE_RE = re.compile(r'^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?$')


def _back(request, tab):
    return redirect(reverse('docker-overview') + f'#{tab}')


def _run(request, tab, func, success):
    try:
        result = func()
        messages.success(request, success(result) if callable(success) else success)
    except PermissionError as e:
        messages.error(request, str(e))
    except docker.errors.APIError as e:
        messages.error(request, f'Docker: {getattr(e, "explanation", None) or e}')
    return _back(request, tab)


@login_required
@superuser_required
def docker_overview(request):
    try:
        data = docker_admin.overview()
    except docker.errors.DockerException as e:
        messages.error(request, f'No se pudo conectar con Docker: {e}')
        data = None
    pulls = Task.objects.filter(kind=Task.Kind.PULL_IMAGE).order_by('-created_at')[:5]
    return render(request, 'orchestrator/docker.html', {'docker': data, 'pulls': pulls})


@login_required
@superuser_required
@require_POST
def docker_container_action(request, container_id, action):
    if action not in ('start', 'stop', 'restart', 'remove'):
        return _back(request, 'containers')
    labels = {'start': 'iniciado', 'stop': 'detenido', 'restart': 'reiniciado', 'remove': 'eliminado'}
    return _run(request, 'containers', lambda: docker_admin.container_action(container_id, action),
                lambda name: f'Contenedor {name} {labels[action]}')


@login_required
@superuser_required
def docker_container_logs(request, container_id):
    try:
        name, logs = docker_admin.container_logs(container_id)
    except docker.errors.NotFound:
        return JsonResponse({'error': 'Contenedor no encontrado'}, status=404)
    return JsonResponse({'name': name, 'logs': logs})


@login_required
@superuser_required
@require_POST
def docker_image_remove(request, image_id):
    return _run(request, 'images', lambda: docker_admin.remove_image(image_id), 'Imagen eliminada')


@login_required
@superuser_required
@require_POST
def docker_image_pull(request):
    reference = request.POST.get('image', '').strip()
    if not IMAGE_REFERENCE_RE.match(reference):
        messages.error(request, 'Nombre de imagen inválido (ej.: odoo:18.0 o nginx:1.27-alpine)')
        return _back(request, 'images')
    enqueue(Task.Kind.PULL_IMAGE, user=request.user, image=reference)
    messages.info(request, f'Descarga de {reference} en cola')
    return _back(request, 'images')


@login_required
@superuser_required
@require_POST
def docker_volume_remove(request, name):
    return _run(request, 'volumes', lambda: docker_admin.remove_volume(name), f'Volumen {name} eliminado')


@login_required
@superuser_required
@require_POST
def docker_network_remove(request, network_id):
    return _run(request, 'networks', lambda: docker_admin.remove_network(network_id), 'Red eliminada')


@login_required
@superuser_required
@require_POST
def docker_prune(request, kind):
    if kind not in ('containers', 'images', 'volumes', 'networks'):
        return _back(request, 'overview')
    # Unused volumes can hold the filestore of a deleted or old instance
    if kind == 'volumes' and request.POST.get('confirm') != 'BORRAR':
        messages.error(request, 'Para eliminar volúmenes sin uso escribe BORRAR en la confirmación')
        return _back(request, 'volumes')
    names = {'containers': 'contenedores', 'images': 'imágenes', 'volumes': 'volúmenes', 'networks': 'redes'}
    return _run(request, kind, lambda: docker_admin.prune(kind),
                lambda result: f'{result[0]} {names[kind]} eliminados · {filesizeformat(result[1])} liberados')
