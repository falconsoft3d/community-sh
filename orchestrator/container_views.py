from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .container_models import Container
from .container_service import ContainerService
from .template_services import get_template_loader

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
            loader = get_template_loader()
            templates_dict = {}
            for tmpl_data in loader.list_available_templates():
                templates_dict[tmpl_data['name']] = loader.get_template_defaults(tmpl_data['name'])
                templates_dict[tmpl_data['name']]['name'] = tmpl_data['display_name']
                templates_dict[tmpl_data['name']]['description'] = tmpl_data['description']
            return render(request, 'orchestrator/container_create.html', {
                'templates': templates_dict
            })
        
        # Get template or custom config
        if template_key and template_key != 'custom':
            loader = get_template_loader()
            template_defaults = loader.get_template_defaults(template_key)
            
            # Check if raw YAML was provided
            yaml_config = request.POST.get('yaml_config')
            if yaml_config:
                try:
                    import yaml
                    template_defaults.update(yaml.safe_load(yaml_config))
                except Exception as e:
                    messages.error(request, f"Error parsing YAML: {str(e)}")
            
            # Use POST values if provided, otherwise use template defaults
            image = request.POST.get('image', template_defaults['image'])
            port = int(request.POST.get('port', template_defaults['default_port']))
            container_port = int(request.POST.get('container_port', template_defaults['container_port']))
            description = request.POST.get('description', template_defaults['description'])
            
            container = Container.objects.create(
                name=name,
                template=template_key,
                image=image,
                port=port,
                container_port=container_port,
                environment=template_defaults.get('environment', {}),
                volumes=template_defaults.get('volumes', {}),
                network=template_defaults.get('network', 'bridge'),
                command=template_defaults.get('command', ''),
                description=description,
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
            loader = get_template_loader()
            templates_dict = {}
            first_template = None
            for tmpl_data in loader.list_available_templates():
                name = tmpl_data['name']
                defaults = loader.get_template_defaults(name)
                templates_dict[name] = defaults
                templates_dict[name]['name'] = tmpl_data['display_name']
                templates_dict[name]['description'] = tmpl_data['description']
                templates_dict[name]['port'] = tmpl_data.get('default_port', 8000)
                templates_dict[name]['raw_yaml'] = loader.get_template_raw(name)
                if not first_template:
                    first_template = templates_dict[name]
                    first_template['key'] = name

            return render(request, 'orchestrator/container_create.html', {
                'templates': templates_dict,
                'first_template': first_template
            })
    
    loader = get_template_loader()
    templates_dict = {}
    first_template = None
    for tmpl_data in loader.list_available_templates():
        name = tmpl_data['name']
        defaults = loader.get_template_defaults(name)
        templates_dict[name] = defaults
        templates_dict[name]['name'] = tmpl_data['display_name']
        templates_dict[name]['description'] = tmpl_data['description']
        templates_dict[name]['port'] = tmpl_data.get('default_port', 8000)
        templates_dict[name]['raw_yaml'] = loader.get_template_raw(name)
        
        if not first_template:
            first_template = templates_dict[name]
            first_template['key'] = name

    return render(request, 'orchestrator/container_create.html', {
        'templates': templates_dict,
        'first_template': first_template
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
