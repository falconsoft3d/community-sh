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
    instances = project.instances.select_related('trial').order_by('name')
    containers = project.containers.order_by('name')
    if not request.user.is_superuser and not can_manage(request.user, project):
        containers = containers.filter(created_by=request.user)
    context = {
        'project': project,
        'containers': containers,
        'instances': paginate(request, instances),
        'all_instances': instances,
        'can_manage': can_manage(request.user, project),
    }
    context['kpis'] = _project_kpis(project)
    if project.trial_enabled and project.trial_slug:
        from django.urls import reverse
        from ..services.trials import active_demos, demo_instances
        context.update(
            trial_page_url=request.build_absolute_uri(reverse('trial-page', args=[project.trial_slug])),
            trial_api_url=request.build_absolute_uri(reverse('trial-api', args=[project.trial_slug])),
            trial_offered=demo_instances(project),
            trial_active=active_demos(project).count(),
            trials=project.trial_requests.select_related('instance', 'source')[:50],
        )
        new_key = request.session.pop('new_trial_api_key', None)
        if new_key and new_key.get('project') == project.pk:
            context['new_trial_api_key'] = new_key['key']
    return render(request, 'orchestrator/project_detail.html', context)


def _project_kpis(project):
    """The figures at the top of a project: its instances, backups, work in progress and its demos."""
    from datetime import timedelta
    from django.utils import timezone
    from django.utils.timesince import timesince
    from ..backup_models import Backup
    from ..task_models import Task
    from ..trial_models import TrialRequest
    now = timezone.now()
    instances = project.instances.all()
    total, running = instances.count(), instances.filter(status='running').count()
    kpis = [{'label': 'Instancias en marcha', 'value': f'{running}/{total}', 'icon': 'server',
             'hint': f'{total - running} parada{"s" if total - running != 1 else ""} o desplegando' if total - running else 'Todas en marcha',
             'tone': 'green' if total and running == total else 'default'}]
    backups = Backup.objects.filter(instance__project=project)
    last = backups.order_by('-created_at').first()
    kpis.append({'label': 'Copias de seguridad', 'value': backups.count(), 'icon': 'archive',
                 'hint': f'Última hace {timesince(last.created_at, now).split(",")[0]}' if last else 'Ninguna todavía',
                 'tone': 'amber' if total and (last is None or now - last.created_at > timedelta(days=7)) else 'default'})
    working = Task.objects.filter(instance__project=project, status__in=['pending', 'running']).count()
    failed = Task.objects.filter(instance__project=project, status='failed', created_at__gte=now - timedelta(days=7)).count()
    containers = project.containers.all()
    if containers.exists():
        up = containers.filter(status='running').count()
        kpis.append({'label': 'Contenedores en marcha', 'value': f'{up}/{containers.count()}', 'icon': 'box',
                     'hint': 'Aplicaciones Docker del proyecto', 'tone': 'green' if up == containers.count() else 'default'})
    kpis.append({'label': 'Tareas en curso', 'value': working, 'icon': 'activity',
                 'hint': f'{failed} fallida{"s" if failed != 1 else ""} en 7 días' if failed else 'Sin fallos en 7 días',
                 'tone': 'red' if failed else 'default'})

    if project.trial_enabled:
        from ..services.trials import active_demos
        demos = project.trial_requests.all()
        active = active_demos(project).count()
        month = demos.filter(created_at__gte=now - timedelta(days=30))
        today = demos.filter(created_at__gte=timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0))
        ready_or_done = month.exclude(status=TrialRequest.Status.FAILED).count()
        failed_demos = month.filter(status=TrialRequest.Status.FAILED).count()
        emailed = month.exclude(emailed_at=None).count()
        kpis += [
            {'label': 'Demos activas', 'value': f'{active}/{project.trial_max_active}', 'icon': 'flask-conical',
             'hint': 'Sin plazas libres' if active >= project.trial_max_active else f'{project.trial_max_active - active} plaza{"s" if project.trial_max_active - active != 1 else ""} libre{"s" if project.trial_max_active - active != 1 else ""}',
             'tone': 'amber' if active >= project.trial_max_active else 'blue'},
            {'label': 'Demos pedidas (30 días)', 'value': ready_or_done, 'icon': 'user-plus',
             'hint': f'{today.count()} hoy · {emailed} enviadas por email', 'tone': 'default'},
            {'label': 'Demos fallidas (30 días)', 'value': failed_demos, 'icon': 'circle-alert',
             'hint': 'Revisa Actividad' if failed_demos else 'Ninguna', 'tone': 'red' if failed_demos else 'default'},
        ]
    # A project that receives demos: how many it holds and how many are about to go
    hosted = TrialRequest.objects.filter(instance__project=project)
    if hosted.exists():
        soon = hosted.filter(status=TrialRequest.Status.READY, expires_at__lte=now + timedelta(days=3)).count()
        kpis.append({'label': 'Demos alojadas', 'value': hosted.count(), 'icon': 'flask-conical',
                     'hint': f'{soon} vence{"n" if soon != 1 else ""} en 3 días o menos' if soon else 'Ninguna vence en 3 días',
                     'tone': 'amber' if soon else 'blue'})
    return kpis


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
