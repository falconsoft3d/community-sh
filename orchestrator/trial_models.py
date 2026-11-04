import secrets

from django.db import models


def generate_trial_token():
    return secrets.token_urlsafe(24)


class TrialRequest(models.Model):
    """A demo asked for on the public page of a project in test mode: a copy of one of its instances."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Creándose'
        READY = 'ready', 'Lista'
        FAILED = 'failed', 'Fallida'
        EXPIRED = 'expired', 'Vencida'

    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='trial_requests',
                                help_text="Project in test mode the demo was asked on")
    source = models.ForeignKey('Instance', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                               help_text="Instance that was copied")
    instance = models.OneToOneField('Instance', on_delete=models.SET_NULL, null=True, blank=True, related_name='trial',
                                    help_text="The copy, in the sibling project")
    task = models.ForeignKey('Task', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    contact = models.ForeignKey('Contact', on_delete=models.SET_NULL, null=True, blank=True, related_name='trials')
    # Secret part of the URL of its status page (whoever has it sees the credentials)
    token = models.CharField(max_length=64, unique=True, default=generate_trial_token)

    name = models.CharField(max_length=150)
    email = models.EmailField()
    company = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    country = models.CharField(max_length=80, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    version = models.CharField(max_length=10, blank=True)
    admin_login = models.CharField(max_length=150, blank=True)
    admin_password = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True, help_text="When its credentials were sent by email")

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['project', 'email', 'created_at'])]

    def __str__(self):
        return f"Demo {self.email} ({self.project})"

    # A demo is stopped when it expires and deleted a week later (services.trials.expire_demos)
    @property
    def delete_at(self):
        from datetime import timedelta
        start = self.stopped_at or self.expires_at
        return start + timedelta(days=7) if start else None

    @staticmethod
    def _days_until(moment):
        import math
        from django.utils import timezone
        if moment is None:
            return None
        return max(0, math.ceil((moment - timezone.now()).total_seconds() / 86400))

    @property
    def days_until_stop(self):
        return self._days_until(self.expires_at)

    @property
    def days_until_delete(self):
        return self._days_until(self.delete_at)
