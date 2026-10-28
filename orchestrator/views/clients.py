"""Clients: user accounts that see and operate the instances of their projects."""
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ClientForm
from ..models import Instance
from ..permissions import superuser_required


def _clients():
    return User.objects.filter(profile__is_client=True).select_related('profile')


@login_required
@superuser_required
def client_list(request):
    clients = _clients().annotate(project_count=Count('client_projects', distinct=True)).order_by('profile__company', 'username')
    instance_counts = dict(
        Instance.objects.filter(project__client__in=clients).values_list('project__client').annotate(Count('id'))
    )
    for client in clients:
        client.instance_count = instance_counts.get(client.pk, 0)
    return render(request, 'orchestrator/client_list.html', {'clients': clients})


@login_required
@superuser_required
def client_create(request):
    form = ClientForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        client, generated = form.save()
        if generated:
            # Shown once: it isn't stored in plain text anywhere
            messages.warning(request, f'Contraseña inicial de {client.username}: {generated} — compártela con el cliente, no se volverá a mostrar.')
        messages.success(request, f'Cliente "{client.profile.company}" creado')
        return redirect('client-detail', pk=client.pk)
    return render(request, 'orchestrator/client_form.html', {'form': form})


@login_required
@superuser_required
def client_detail(request, pk):
    client = get_object_or_404(_clients(), pk=pk)
    projects = client.client_projects.annotate(instance_count=Count('instances')).order_by('name')
    return render(request, 'orchestrator/client_detail.html', {
        'client': client,
        'projects': projects,
        'instances': Instance.objects.filter(project__client=client).select_related('project').order_by('project__name', 'name'),
    })


@login_required
@superuser_required
def client_edit(request, pk):
    client = get_object_or_404(_clients(), pk=pk)
    form = ClientForm(request.POST or None, client=client)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Cliente actualizado')
        return redirect('client-detail', pk=client.pk)
    return render(request, 'orchestrator/client_form.html', {'form': form, 'client': client})


@login_required
@superuser_required
@require_POST
def client_reset_password(request, pk):
    client = get_object_or_404(_clients(), pk=pk)
    password = secrets.token_urlsafe(12)
    client.set_password(password)
    client.save()
    messages.warning(request, f'Nueva contraseña de {client.username}: {password} — compártela con el cliente, no se volverá a mostrar.')
    return redirect('client-detail', pk=pk)


@login_required
@superuser_required
@require_POST
def client_toggle_active(request, pk):
    client = get_object_or_404(_clients(), pk=pk)
    client.is_active = not client.is_active
    client.save(update_fields=['is_active'])
    messages.success(request, 'Acceso activado' if client.is_active else 'Acceso desactivado: el cliente ya no puede entrar')
    return redirect('client-detail', pk=pk)


@login_required
@superuser_required
@require_POST
def client_delete(request, pk):
    client = get_object_or_404(_clients(), pk=pk)
    name = client.profile.company or client.username
    # Projects stay (client is SET_NULL); only the access goes away
    client.delete()
    messages.success(request, f'Cliente "{name}" eliminado. Sus proyectos e instancias se mantienen.')
    return redirect('client-list')
