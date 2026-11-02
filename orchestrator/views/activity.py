"""Activity: every task of the worker (deploys, backups, restores, installs...) with its live log and progress."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from ..pagination import paginate
from ..permissions import instances_for
from ..task_models import Task

LIVE_LOG_CHARS = 20_000


def tasks_for(user):
    """The tasks of the instances the user sees, and the ones the user launched."""
    tasks = Task.objects.select_related('instance', 'created_by')
    if user.is_superuser:
        return tasks
    return tasks.filter(Q(instance__in=instances_for(user)) | Q(created_by=user))


def task_live_data(task, full=False):
    return {
        'id': task.id,
        'status': task.status,
        'status_display': task.get_status_display(),
        'active': task.is_active,
        'progress': task.bar_percent,
        'step': task.step,
        'log': task.log if full else task.log[-LIVE_LOG_CHARS:],
        'duration': task.duration,
        'duration_display': task.duration_display,
    }


@login_required
def activity_list(request):
    tasks = tasks_for(request.user)
    status = request.GET.get('status', '')
    kind = request.GET.get('kind', '')
    search = request.GET.get('q', '').strip()
    if status in Task.Status.values:
        tasks = tasks.filter(status=status)
    if kind in Task.Kind.values:
        tasks = tasks.filter(kind=kind)
    if search:
        tasks = tasks.filter(Q(instance__name__icontains=search) | Q(created_by__username__icontains=search)
                             | Q(step__icontains=search) | Q(result__icontains=search))
    page = paginate(request, tasks.order_by('-created_at'))
    visible = tasks_for(request.user)
    return render(request, 'orchestrator/activity_list.html', {
        'tasks': page,
        'statuses': Task.Status.choices,
        'kinds': Task.Kind.choices,
        'selected_status': status,
        'selected_kind': kind,
        'search': search,
        'active_count': visible.filter(status__in=(Task.Status.PENDING, Task.Status.RUNNING)).count(),
        'failed_count': visible.filter(status=Task.Status.FAILED).count(),
    })


@login_required
def activity_detail(request, pk):
    task = get_object_or_404(tasks_for(request.user), pk=pk)
    return render(request, 'orchestrator/activity_detail.html', {'task': task})


@login_required
def task_live(request):
    """Progress, step and log of the tasks asked for (?ids=1,2), polled by the pages while they run (&full=1: the whole log)."""
    ids = [int(value) for value in request.GET.get('ids', '').split(',') if value.strip().isdigit()][:50]
    tasks = tasks_for(request.user).filter(pk__in=ids)
    full = request.GET.get('full') == '1'
    return JsonResponse({'tasks': [task_live_data(task, full) for task in tasks]})
