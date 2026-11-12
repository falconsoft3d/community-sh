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
    # Older tokens: no expiry and full access, as when they were made
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Stops working after this moment (empty: never)")
    read_only = models.BooleanField(default=False, help_text="Only reads: GET in the API, the list_/get_ tools in MCP")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (…{self.hint})"

    @classmethod
    def issue(cls, user, name, days=None, read_only=False):
        """Create a token; the plain value is returned once and never stored. days: lifetime (None: never expires)."""
        from datetime import timedelta
        from django.utils import timezone
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = cls.objects.create(user=user, name=name, token_hash=hash_token(token), hint=token[-6:], read_only=read_only,
                                    expires_at=timezone.now() + timedelta(days=days) if days else None)
        return record, token

    @property
    def expired(self):
        from django.utils import timezone
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @classmethod
    def authenticate(cls, authorization):
        """The token of an "Authorization: Bearer csh_..." header, when it works: known, not expired, an active
        user who has 2FA if the platform requires it. Its last use is recorded. None otherwise."""
        from django.utils import timezone
        if not (authorization or '').startswith('Bearer '):
            return None
        token = cls.objects.select_related('user').filter(token_hash=hash_token(authorization[7:].strip())).first()
        if token is None or token.expired or not token.user.is_active:
            return None
        from .permissions import missing_required_2fa
        if missing_required_2fa(token.user):
            return None
        cls.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token
