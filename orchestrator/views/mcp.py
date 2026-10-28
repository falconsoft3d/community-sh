"""MCP endpoint for Claude and the personal tokens that authenticate it."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..mcp_models import MCPToken, hash_token
from ..permissions import get_global_config
from ..services.mcp_server import handle_message


def _token_user(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    token = MCPToken.objects.select_related('user').filter(token_hash=hash_token(header[7:].strip())).first()
    if token is None or not token.user.is_active:
        return None
    MCPToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.user


@csrf_exempt
def mcp_endpoint(request):
    """Streamable HTTP transport: JSON-RPC over POST, answered with application/json (no SSE stream)."""
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response
    config = get_global_config()
    if not config or not config.mcp_enabled:
        return JsonResponse({'error': 'MCP is disabled (Settings → MCP)'}, status=404)
    user = _token_user(request)
    if user is None:
        response = JsonResponse({'error': 'Invalid or missing token'}, status=401)
        response['WWW-Authenticate'] = 'Bearer'
        return response
    try:
        payload = json.loads(request.body or b'null')
    except ValueError:
        return JsonResponse({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}, status=400)

    if isinstance(payload, list):
        replies = [reply for reply in (handle_message(user, m) for m in payload) if reply is not None]
        return JsonResponse(replies, safe=False) if replies else HttpResponse(status=202)
    reply = handle_message(user, payload)
    return JsonResponse(reply) if reply is not None else HttpResponse(status=202)


@login_required
@require_POST
def mcp_token_create(request):
    name = request.POST.get('name', '').strip()[:100] or 'Claude'
    _record, token = MCPToken.issue(request.user, name)
    messages.warning(request, f'Token "{name}" creado: {token} — cópialo ahora, no se volverá a mostrar.')
    return redirect(reverse('settings') + '#mcp')


@login_required
@require_POST
def mcp_token_revoke(request, token_id):
    MCPToken.objects.filter(pk=token_id, user=request.user).delete()
    messages.success(request, 'Token revocado')
    return redirect(reverse('settings') + '#mcp')
