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

from ..mcp_models import MCPToken
from ..permissions import get_global_config
from ..services.mcp_server import handle_message
from ..reauth import recent_auth_required


TOKEN_DAYS = (30, 90, 365, 0)


def _token_options(request):
    """(days, read_only) from the form: 90 days unless another lifetime (0: never) is chosen."""
    try:
        days = int(request.POST.get('days', 90))
    except ValueError:
        days = 90
    return (days if days in TOKEN_DAYS else 90) or None, request.POST.get('read_only') == '1'


def _token(request):
    return MCPToken.authenticate(request.headers.get('Authorization', ''))


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
    token = _token(request)
    if token is None:
        response = JsonResponse({'error': 'Invalid or missing token'}, status=401)
        response['WWW-Authenticate'] = 'Bearer'
        return response
    from ..ratelimit import MCP_PER_MINUTE, hit
    if hit(f'mcp:{token.pk}', MCP_PER_MINUTE, 60):
        response = JsonResponse({'error': f'Too many requests: at most {MCP_PER_MINUTE} a minute per token'}, status=429)
        response['Retry-After'] = '60'
        return response
    try:
        payload = json.loads(request.body or b'null')
    except ValueError:
        return JsonResponse({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}, status=400)

    if isinstance(payload, list):
        replies = [reply for reply in (handle_message(token.user, m, read_only=token.read_only) for m in payload)
                   if reply is not None]
        return JsonResponse(replies, safe=False) if replies else HttpResponse(status=202)
    reply = handle_message(token.user, payload, read_only=token.read_only)
    return JsonResponse(reply) if reply is not None else HttpResponse(status=202)


@login_required
@require_POST
@recent_auth_required
def mcp_token_create(request):
    tab = _token_tab(request)
    name = request.POST.get('name', '').strip()[:100] or ('API' if tab == 'api' else 'Claude')
    days, read_only = _token_options(request)
    _record, token = MCPToken.issue(request.user, name, days=days, read_only=read_only)
    from ..audit import record
    record(request, 'token_created', name, f"Pestaña {tab} · {f'{days} días' if days else 'sin caducidad'}"
                                           f"{' · solo lectura' if read_only else ''}")
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
    days, read_only = _token_options(request)
    _record, token = MCPToken.issue(request.user, name, days=days, read_only=read_only)
    from ..audit import record
    record(request, 'token_created', name, f"Fichero .md para una IA · {f'{days} días' if days else 'sin caducidad'}"
                                           f"{' · solo lectura' if read_only else ''}")
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
