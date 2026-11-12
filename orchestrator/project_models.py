from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.contrib.auth.models import User


# Palette for project cards and tags (Tailwind colour names, used in the templates)
COLORS = [('', 'Sin color'), ('slate', 'Gris'), ('blue', 'Azul'), ('teal', 'Turquesa'), ('green', 'Verde'),
          ('amber', 'Ámbar'), ('orange', 'Naranja'), ('red', 'Rojo'), ('pink', 'Rosa'), ('violet', 'Violeta')]
TAG_COLORS = [value for value, _label in COLORS if value]


class ProjectTag(models.Model):
    """A label for projects (each user has their own), to group and filter them."""
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_tags')
    name = models.CharField(max_length=40)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['owner', 'name'], name='unique_project_tag_per_owner')]

    def __str__(self):
        return self.name

    @property
    def color(self):
        """Always the same colour for the same name."""
        import hashlib
        return TAG_COLORS[int(hashlib.md5(self.name.lower().encode()).hexdigest(), 16) % len(TAG_COLORS)]


class Project(models.Model):
    """Groups the instances of one client or initiative (e.g. production, staging, tests)."""
    name = models.CharField(max_length=100)
    client = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_projects',
        help_text="Usuario cliente que ve y opera este proyecto",
    )
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects')
    color = models.CharField(max_length=10, blank=True, default='', choices=COLORS, help_text="Background of its card")
    tags = models.ManyToManyField(ProjectTag, blank=True, related_name='projects')

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
    # Key for a website's backend to ask for demos of this project through the API, without the captcha
    trial_api_key_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 of the demo API key")
    trial_api_key_hint = models.CharField(max_length=8, blank=True, help_text="Last characters, to recognise it")
    trial_max_active = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(50)], help_text="Demos running at the same time (each one is an Odoo and a PostgreSQL)")
    # What its client may do (whoever manages the project always may). The defaults are what clients could always do
    client_can_operate = models.BooleanField(default=True, help_text="Deploy, restart and stop its instances")
    client_can_backups = models.BooleanField(default=True, help_text="Create and download backups")
    client_can_logs = models.BooleanField(default=True, help_text="See the Odoo logs")
    client_can_restore = models.BooleanField(default=False, help_text="Restore one of its backups")
    client_can_admin_login = models.BooleanField(default=False, help_text="Log into its Odoo as administrator")

    # Quotas, set by an administrator (0: no limit)
    max_instances = models.PositiveSmallIntegerField(default=0, help_text="Instances the project can have (0: no limit)")
    max_memory_mb = models.PositiveIntegerField(default=0, help_text="RAM its instances' memory limits can add up to, in MB (0: no limit)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'name'], name='unique_project_name_per_owner'),
        ]

    def __str__(self):
        return self.name

    def new_trial_api_key(self):
        """A new demo API key (the previous one stops working). Returned once: only its hash is stored."""
        import hashlib
        import secrets
        key = f'csh_demo_{secrets.token_urlsafe(32)}'
        self.trial_api_key_hash = hashlib.sha256(key.encode()).hexdigest()
        self.trial_api_key_hint = key[-4:]
        self.save(update_fields=['trial_api_key_hash', 'trial_api_key_hint'])
        return key

    def trial_api_key_ok(self, key):
        import hashlib
        import hmac
        if not self.trial_api_key_hash or not key:
            return False
        return hmac.compare_digest(self.trial_api_key_hash, hashlib.sha256(key.encode()).hexdigest())

    @property
    def tag_list(self):
        return [tag.name for tag in self.tags.all()]

    @property
    def client_display(self):
        if not self.client:
            return ''
        return self.client.profile.company or self.client.get_full_name() or self.client.username
