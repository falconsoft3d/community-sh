import re

from django.db import models

REPO_URL_RE = re.compile(r'^https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+?(\.git)?$')


class InstanceRepository(models.Model):
    """Extra addons repository of an instance, cloned next to the main one and added to addons_path."""
    instance = models.ForeignKey('Instance', on_delete=models.CASCADE, related_name='repositories')
    url = models.CharField(max_length=300, help_text="HTTPS clone URL, e.g. https://github.com/OCA/web.git")
    branch = models.CharField(max_length=100, default='main')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [models.UniqueConstraint(fields=['instance', 'url'], name='unique_repository_per_instance')]

    def __str__(self):
        return f"{self.slug}@{self.branch}"

    @property
    def slug(self):
        """Folder name: the repo name ('web' for .../OCA/web.git), plus the owner if needed to stay unique."""
        parts = [p for p in self.url.rstrip('/').removesuffix('.git').split('/') if p]
        return re.sub(r'[^A-Za-z0-9._-]', '_', '-'.join(parts[-2:]) if len(parts) >= 2 else parts[-1])
