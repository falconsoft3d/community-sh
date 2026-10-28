from django.db import models
from django.contrib.auth.models import User


class Project(models.Model):
    """Groups the instances of one client or initiative (e.g. production, staging, tests)."""
    name = models.CharField(max_length=100)
    client = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_projects',
        help_text="Usuario cliente que ve y opera este proyecto",
    )
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
        return self.name

    @property
    def client_display(self):
        if not self.client:
            return ''
        return self.client.profile.company or self.client.get_full_name() or self.client.username
