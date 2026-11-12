"""Auditoría: who did what in the panel (administrators)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from ..audit import ACTIONS
from ..audit_models import AuditEvent
from ..pagination import paginate
from ..permissions import superuser_required


@login_required
@superuser_required
def audit_list(request):
    events = AuditEvent.objects.all()
    action = request.GET.get('action', '')
    username = request.GET.get('user', '').strip()
    query = request.GET.get('q', '').strip()
    if action in ACTIONS:
        events = events.filter(action=action)
    if username:
        events = events.filter(username=username)
    if query:
        events = events.filter(target__icontains=query)
    page = paginate(request, events)
    for event in page:
        event.label = ACTIONS.get(event.action, event.action)
    return render(request, 'orchestrator/audit_list.html', {
        'events': page, 'actions': ACTIONS, 'action': action, 'username': username, 'query': query,
        'usernames': AuditEvent.objects.exclude(username='').values_list('username', flat=True).distinct().order_by('username'),
    })
