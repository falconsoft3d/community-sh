"""Servers (nodes) where instances can run besides this one: superusers only."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..audit import record
from ..models import Instance
from ..permissions import superuser_required
from ..server_models import PanelKey, Server
from ..task_models import Task
from ..tasks import enqueue


class ServerForm(forms.ModelForm):
    class Meta:
        model = Server
        fields = ['name', 'host', 'ssh_user', 'ssh_port', 'workdir', 'notes']
        labels = {'name': 'Nombre', 'host': 'IP privada', 'ssh_user': 'Usuario SSH', 'ssh_port': 'Puerto SSH',
                  'workdir': 'Carpeta de trabajo', 'notes': 'Notas'}
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'nodo-1'}),
                   'host': forms.TextInput(attrs={'placeholder': '10.0.0.3'}),
                   'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'CPX32 hel1, para clientes de pruebas...'})}

    def clean_ssh_port(self):
        port = self.cleaned_data['ssh_port']
        if not 1 <= port <= 65535:
            raise forms.ValidationError('Puerto no válido')
        return port


def _setup_pending(server):
    return Task.objects.filter(kind=Task.Kind.SERVER_SETUP, params__server=server.pk,
                               status__in=[Task.Status.PENDING, Task.Status.RUNNING]).exists()


@login_required
@superuser_required
def server_list(request):
    from ..services.nodes import bootstrap_command
    form = ServerForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        server = form.save()
        record(request, 'server_added', server.name, server.host)
        enqueue(Task.Kind.SERVER_SETUP, None, request.user, server=server.pk)
        messages.success(request, f'Servidor {server.name} añadido: se está comprobando y preparando')
        return redirect('server-list')
    servers = list(Server.objects.all())
    for server in servers:
        server.instance_list = list(server.instances.order_by('name'))
        server.container_list = list(server.containers.order_by('name'))
        server.setup_pending = _setup_pending(server)
        last = Task.objects.filter(kind=Task.Kind.SERVER_SETUP, params__server=server.pk).order_by('-created_at').first()
        server.last_task = last
    public_key = PanelKey.current()
    return render(request, 'orchestrator/server_list.html', {
        'servers': servers, 'form': form, 'public_key': public_key,
        'bootstrap': bootstrap_command(public_key) if public_key else '',
        'local_instances': Instance.objects.filter(server=None).count(),
    })


@login_required
@superuser_required
@require_POST
def server_setup(request, pk):
    server = get_object_or_404(Server, pk=pk)
    if _setup_pending(server):
        messages.info(request, f'{server.name} ya se está preparando')
    else:
        enqueue(Task.Kind.SERVER_SETUP, None, request.user, server=server.pk)
        messages.success(request, f'Comprobando y preparando {server.name}')
    return redirect('server-list')


@login_required
@superuser_required
@require_POST
def server_toggle(request, pk):
    server = get_object_or_404(Server, pk=pk)
    server.active = not server.active
    server.save(update_fields=['active'])
    record(request, 'server_changed', server.name, 'admite instancias nuevas' if server.active else 'no admite instancias nuevas')
    messages.success(request, f'{server.name} {"admite" if server.active else "ya no admite"} instancias nuevas')
    return redirect('server-list')


@login_required
@superuser_required
@require_POST
def server_delete(request, pk):
    server = get_object_or_404(Server, pk=pk)
    count, containers = server.instances.count(), server.containers.count()
    if count or containers:
        messages.error(request, f'{server.name} tiene {count} instancia(s) y {containers} contenedor(es): '
                                'muévelos o elimínalos antes de quitar el servidor')
        return redirect('server-list')
    from ..services.nodes import forget_client
    forget_client(server)
    record(request, 'server_deleted', server.name, server.host)
    server.delete()
    messages.success(request, f'Servidor {server.name} quitado del panel (el servidor en sí no se toca)')
    return redirect('server-list')
