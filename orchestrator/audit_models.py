from django.contrib.auth.models import User
from django.db import models


class AuditEvent(models.Model):
    """Who did what in the panel: sign-ins, passwords shown or copied, settings, tokens, users and instance changes."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_events')
    username = models.CharField(max_length=150, blank=True, help_text="Kept if the user is deleted")
    action = models.CharField(max_length=60, db_index=True)
    target = models.CharField(max_length=255, blank=True, help_text="What it was about, e.g. the instance name")
    details = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action} {self.target}'
