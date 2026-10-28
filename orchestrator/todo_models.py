from django.contrib.auth.models import User
from django.db import models


class Todo(models.Model):
    """Work item for the platform: added by people, completed by them or by Claude (via MCP)."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        IN_PROGRESS = 'in_progress', 'En curso'
        DONE = 'done', 'Completada'

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='todos')
    completed_by = models.CharField(max_length=150, blank=True, help_text="Who completed it (user or 'Claude')")
    completion_note = models.TextField(blank=True, help_text="What was done")
    completed_in_version = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def set_status(self, status, by='', note=''):
        from django.utils import timezone
        from config.version import VERSION
        self.status = status
        if status == self.Status.DONE:
            self.completed_at = timezone.now()
            self.completed_by = by
            self.completion_note = note or self.completion_note
            self.completed_in_version = VERSION
        else:
            self.completed_at = None
            self.completed_by = ''
            self.completed_in_version = ''
        self.save()
