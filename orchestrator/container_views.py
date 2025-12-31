from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .container_models import Container
from .container_service import ContainerService
from .container_templates import CONTAINER_TEMPLATES

@login_required
def container_list(request):
    """List all containers"""
    containers = Container.objects.filter(created_by=request.user)
    return render(request, 'orchestrator/container_list.html', {'containers': containers})

@login_required
def container_create(request):
    """Create a new container"""
    if request.method == 'POST':
        template_key = request.POST.get('template')
        name = request.POST.get('name')
        
        # Check if name already exists
        if Container.objects.filter(name=name).exists():
            messages.error(request, f'Container with name "{name}" already exists')
            return render(request, 'orchestrator/container_create.html', {
                'templates': CONTAINER_TEMPLATES
            })
        
        # Get template or custom config
        if template_key and template_key != 'custom':
            template = CONTAINER_TEMPLATES.get(template_key)
            container = Container.objects.create(
                name=name,
                template=template_key,
                image=template['image'],
                port=int(request.POST.get('port', template['port'])),
                container_port=template['container_port'],
                environment=template['environment'],
                volumes=template['volumes'],
                network=template['network'],
                description=template['description'],
                created_by=request.user
            )
        else:
            # Custom container
            container = Container.objects.create(
                name=name,
                template='custom',
                image=request.POST.get('image'),
                port=int(request.POST.get('port')),
                container_port=int(request.POST.get('container_port')),
                environment={},
                volumes={},
                network='bridge',
                description=request.POST.get('description', ''),
                created_by=request.user
            )
        
        # Create and start container
        service = ContainerService()
        success, message = service.create_container(container)
        
        if success:
            messages.success(request, message)
            return redirect('container-detail', pk=container.pk)
        else:
            messages.error(request, message)
            container.delete()
            return render(request, 'orchestrator/container_create.html', {
                'templates': CONTAINER_TEMPLATES
            })
    
    return render(request, 'orchestrator/container_create.html', {
        'templates': CONTAINER_TEMPLATES
    })

@login_required
def container_detail(request, pk):
    """Container detail view"""
    container = get_object_or_404(Container, pk=pk, created_by=request.user)
    
    # Get container logs if running
    logs = None
    if container.status == 'running':
        service = ContainerService()
        logs = service.get_container_logs(container, tail=50)
    
    return render(request, 'orchestrator/container_detail.html', {
        'container': container,
        'logs': logs
    })

@login_required
def container_start(request, pk):
    """Start a container"""
    container = get_object_or_404(Container, pk=pk, created_by=request.user)
    service = ContainerService()
    success, message = service.start_container(container)
    
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    
    return redirect('container-detail', pk=pk)

@login_required
def container_stop(request, pk):
    """Stop a container"""
    container = get_object_or_404(Container, pk=pk, created_by=request.user)
    service = ContainerService()
    success, message = service.stop_container(container)
    
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    
    return redirect('container-detail', pk=pk)

@login_required
def container_restart(request, pk):
    """Restart a container"""
    container = get_object_or_404(Container, pk=pk, created_by=request.user)
    service = ContainerService()
    success, message = service.restart_container(container)
    
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    
    return redirect('container-detail', pk=pk)

@login_required
def container_delete(request, pk):
    """Delete a container"""
    container = get_object_or_404(Container, pk=pk, created_by=request.user)
    
    if request.method == 'POST':
        service = ContainerService()
        success, message = service.delete_container(container)
        
        if success:
            container.delete()
            messages.success(request, message)
            return redirect('container-list')
        else:
            messages.error(request, message)
            return redirect('container-detail', pk=pk)
    
    return redirect('container-detail', pk=pk)
