"""Todo: work items the team adds and marks done (Claude can too, through MCP)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..permissions import management_required
from ..todo_models import Todo


def todos_for(user):
    return Todo.objects.all() if user.is_superuser else Todo.objects.filter(created_by=user)


@login_required
@management_required
def todo_list(request):
    todos = todos_for(request.user).select_related('created_by')
    counts = {status: todos.filter(status=status).count() for status in Todo.Status.values}
    total = sum(counts.values())
    return render(request, 'orchestrator/todo_list.html', {
        'pending': todos.exclude(status=Todo.Status.DONE).order_by('status', 'created_at'),
        'done': todos.filter(status=Todo.Status.DONE).order_by('-completed_at')[:50],
        'statuses': Todo.Status.choices,
        'kpis': {
            'done': counts[Todo.Status.DONE],
            'open': total - counts[Todo.Status.DONE],
            'in_progress': counts[Todo.Status.IN_PROGRESS],
            'percent': round(counts[Todo.Status.DONE] * 100 / total) if total else 0,
        },
    })


@login_required
@management_required
@require_POST
def todo_create(request):
    title = request.POST.get('title', '').strip()[:200]
    if not title:
        messages.error(request, 'Escribe el título de la tarea')
    else:
        Todo.objects.create(title=title, description=request.POST.get('description', '').strip(), created_by=request.user)
    return redirect('todo-list')


@login_required
@management_required
@require_POST
def todo_status(request, pk):
    todo = get_object_or_404(todos_for(request.user), pk=pk)
    status = request.POST.get('status')
    if status in Todo.Status.values:
        todo.set_status(status, by=request.user.get_full_name() or request.user.username, note=request.POST.get('note', '').strip())
    return redirect('todo-list')


@login_required
@management_required
@require_POST
def todo_edit(request, pk):
    todo = get_object_or_404(todos_for(request.user), pk=pk)
    title = request.POST.get('title', '').strip()[:200]
    if not title:
        messages.error(request, 'Escribe el título de la tarea')
    else:
        todo.title, todo.description = title, request.POST.get('description', '').strip()
        todo.save(update_fields=['title', 'description', 'updated_at'])
    return redirect('todo-list')


@login_required
@management_required
@require_POST
def todo_delete(request, pk):
    get_object_or_404(todos_for(request.user), pk=pk).delete()
    messages.success(request, 'Tarea eliminada')
    return redirect('todo-list')
