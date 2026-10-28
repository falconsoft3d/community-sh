import hashlib
import secrets

from django.contrib.auth.models import User
from django.db import models

TOKEN_PREFIX = 'csh_'


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


class MCPToken(models.Model):
    """Personal token for the MCP server: Claude acts with this user's permissions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mcp_tokens')
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    hint = models.CharField(max_length=12, help_text="Last characters, to recognise the token")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (…{self.hint})"

    @classmethod
    def issue(cls, user, name):
        """Create a token; the plain value is returned once and never stored."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = cls.objects.create(user=user, name=name, token_hash=hash_token(token), hint=token[-6:])
        return record, token
