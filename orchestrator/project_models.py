from django.core.validators import MaxValueValidator, MinValueValidator
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

    # Test mode: a public page at /<trial_slug>/ where anyone asks for a demo of one of its instances,
    # copied into trial_target_project (a sibling project) with its own admin password
    trial_enabled = models.BooleanField(default=False, help_text="Public demo page for the instances of this project")
    trial_slug = models.SlugField(max_length=50, unique=True, null=True, blank=True,
                                  help_text="Public URL of the demo page: https://domain/<slug>")
    trial_days = models.PositiveSmallIntegerField(default=15, validators=[MinValueValidator(1), MaxValueValidator(365)],
                                                  help_text="Days a demo lasts")
    trial_target_project = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                             related_name='trial_sources', help_text="Sibling project that holds the demos")
    trial_message = models.TextField(blank=True, help_text="Text shown on the demo page")
    trial_max_active = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(50)], help_text="Demos running at the same time (each one is an Odoo and a PostgreSQL)")
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
