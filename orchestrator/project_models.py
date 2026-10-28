from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    """Groups the instances of one client or initiative (e.g. production, staging, tests)."""
    name = models.CharField(max_length=100)
    client = models.CharField(max_length=150, blank=True, help_text="Cliente al que pertenece el proyecto (opcional)")
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'name'], name='unique_project_name_per_owner'),
        ]

    def __str__(self):
        return f"{self.name} ({self.client})" if self.client else self.name
