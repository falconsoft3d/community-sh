"""Projects: group a client's instances (production, staging, tests...)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..forms import ProjectForm
from ..pagination import paginate
from ..permissions import can_manage, get_project_for_user, management_required, projects_for


@login_required
def project_list(request):
    projects = projects_for(request.user).annotate(
        instance_count=Count('instances'),
        running_count=Count('instances', filter=Q(instances__status='running')),
    ).select_related('owner').order_by('name')
    return render(request, 'orchestrator/project_list.html', {'projects': paginate(request, projects)})


@login_required
@management_required
def project_create(request):
    form = ProjectForm(request.POST or None, owner=request.user, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.instance.owner = request.user
        project = form.save()
        messages.success(request, f'Proyecto "{project.name}" creado')
        return redirect('project-detail', pk=project.pk)
    return render(request, 'orchestrator/project_form.html', {'form': form})


@login_required
def project_detail(request, pk):
    project = get_project_for_user(request.user, pk)
    instances = project.instances.order_by('name')
    return render(request, 'orchestrator/project_detail.html', {
        'project': project,
        'instances': paginate(request, instances),
        'all_instances': instances,
        'can_manage': can_manage(request.user, project),
    })


@login_required
def project_edit(request, pk):
    project = get_project_for_user(request.user, pk, manage=True)
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Proyecto actualizado')
        return redirect('project-detail', pk=project.pk)
    return render(request, 'orchestrator/project_form.html', {'form': form, 'project': project})


@login_required
@require_POST
def project_delete(request, pk):
    """Delete a project; with instances, they are all destroyed too (typed name confirmation)."""
    from ..task_models import Task
    from ..tasks import enqueue
    project = get_project_for_user(request.user, pk, manage=True)
    if not project.instances.exists():
        name = project.name
        project.delete()
        messages.success(request, f'Proyecto "{name}" eliminado')
        return redirect('project-list')
    if request.POST.get('confirm', '').strip() != project.name:
        messages.error(request, 'Para eliminar el proyecto y todas sus instancias escribe su nombre exacto en la confirmación')
        return redirect('project-detail', pk=pk)
    if Task.objects.filter(kind=Task.Kind.DELETE_PROJECT, params__project_id=project.pk, status__in=['pending', 'running']).exists():
        messages.info(request, 'La eliminación de este proyecto ya está en curso')
        return redirect('project-list')
    enqueue(Task.Kind.DELETE_PROJECT, user=request.user, project_id=project.pk)
    count = project.instances.count()
    messages.warning(request, f'Eliminación de "{project.name}" y sus {count} instancias en cola. Desaparecerán en unos minutos.')
    return redirect('project-list')
