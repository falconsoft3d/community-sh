from rest_framework import authentication, exceptions, permissions

from .mcp_models import MCPToken


class PersonalTokenAuthentication(authentication.BaseAuthentication):
    """Authorization: Bearer csh_... — the same personal tokens used by the MCP server."""

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return None
        token = MCPToken.authenticate(header)
        if token is None:
            raise exceptions.AuthenticationFailed('Invalid or expired token (or 2FA setup required)')
        # A read-only token never changes anything, whatever the view allows
        if token.read_only and request.method not in permissions.SAFE_METHODS:
            raise exceptions.PermissionDenied('Read-only token')
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer'
