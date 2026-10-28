from django.utils import timezone
from rest_framework import authentication, exceptions

from .mcp_models import MCPToken, hash_token


class PersonalTokenAuthentication(authentication.BaseAuthentication):
    """Authorization: Bearer csh_... — the same personal tokens used by the MCP server."""

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return None
        token = MCPToken.objects.select_related('user').filter(token_hash=hash_token(header[7:].strip())).first()
        if token is None or not token.user.is_active:
            raise exceptions.AuthenticationFailed('Invalid token')
        MCPToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer'
