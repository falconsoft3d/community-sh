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
from ..reauth import recent_auth_required


def _token_user(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    token = MCPToken.objects.select_related('user').filter(token_hash=hash_token(header[7:].strip())).first()
    if token is None or not token.user.is_active:
        return None
    from ..permissions import missing_required_2fa
    if missing_required_2fa(token.user):
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
@recent_auth_required
def mcp_token_create(request):
    tab = _token_tab(request)
    name = request.POST.get('name', '').strip()[:100] or ('API' if tab == 'api' else 'Claude')
    _record, token = MCPToken.issue(request.user, name)
    from ..audit import record
    record(request, 'token_created', name, 'Pestaña ' + tab)
    # Shown once on the next settings page (with a copy button), then dropped
    request.session['new_personal_token'] = {'name': name, 'token': token}
    return redirect(reverse('settings') + f'#{tab}')


@login_required
@require_POST
def mcp_token_revoke(request, token_id):
    from ..audit import record
    for token in MCPToken.objects.filter(pk=token_id, user=request.user):
        record(request, 'token_revoked', token.name, f'…{token.hint}')
    MCPToken.objects.filter(pk=token_id, user=request.user).delete()
    messages.success(request, 'Token revocado')
    return redirect(reverse('settings') + f'#{_token_tab(request)}')


@login_required
@require_POST
@recent_auth_required
def api_token_markdown(request):
    """Settings → API: a new personal token and the API documentation in one .md file, to hand to an AI."""
    from ..api_docs import api_markdown
    from ..permissions import missing_required_2fa
    if missing_required_2fa(request.user):
        messages.error(request, 'Activa la verificación en dos pasos (2FA) en tu perfil: sin ella los tokens no funcionan')
        return redirect(reverse('settings') + '#api')
    name = request.POST.get('name', '').strip()[:100] or f'IA {timezone.localtime():%d/%m/%Y %H:%M}'
    _record, token = MCPToken.issue(request.user, name)
    from ..audit import record
    record(request, 'token_created', name, 'Fichero .md para una IA')
    config = get_global_config()
    mcp_url = request.build_absolute_uri(reverse('mcp')) if config and config.mcp_enabled else ''
    content = api_markdown(request.user, request.build_absolute_uri('/api/'), token, name, mcp_url=mcp_url)
    response = HttpResponse(content, content_type='text/markdown; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="community-sh-api.md"'
    # It carries a secret: never kept by a cache
    response['Cache-Control'] = 'no-store'
    return response


def _token_tab(request):
    return 'api' if request.POST.get('tab') == 'api' else 'mcp'
