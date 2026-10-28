"""Projects: group a client's instances (production, staging, tests...)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..forms import ProjectForm
from ..permissions import get_project_for_user, projects_for


@login_required
def project_list(request):
    projects = projects_for(request.user).annotate(
        instance_count=Count('instances'),
        running_count=Count('instances', filter=Q(instances__status='running')),
    ).select_related('owner')
    return render(request, 'orchestrator/project_list.html', {'projects': projects})


@login_required
def project_create(request):
    form = ProjectForm(request.POST or None, owner=request.user)
    if request.method == 'POST' and form.is_valid():
        form.instance.owner = request.user
        project = form.save()
        messages.success(request, f'Proyecto "{project.name}" creado')
        return redirect('project-detail', pk=project.pk)
    return render(request, 'orchestrator/project_form.html', {'form': form})


@login_required
def project_detail(request, pk):
    project = get_project_for_user(request.user, pk)
    return render(request, 'orchestrator/project_detail.html', {
        'project': project,
        'instances': project.instances.order_by('name'),
    })


@login_required
def project_edit(request, pk):
    project = get_project_for_user(request.user, pk)
    form = ProjectForm(request.POST or None, instance=project)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Proyecto actualizado')
        return redirect('project-detail', pk=project.pk)
    return render(request, 'orchestrator/project_form.html', {'form': form, 'project': project})


@login_required
@require_POST
def project_delete(request, pk):
    project = get_project_for_user(request.user, pk)
    if project.instances.exists():
        messages.error(request, 'El proyecto tiene instancias: elimínalas o muévelas a otro proyecto antes de borrarlo')
        return redirect('project-detail', pk=pk)
    project.delete()
    messages.success(request, f'Proyecto "{project.name}" eliminado')
    return redirect('project-list')
