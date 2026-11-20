"""
Servers (nodes) where instances can run besides the panel's own server. The panel stays the brain: it keeps
the code of every instance, its database of record and Traefik; a node only runs Docker (the odoo_* and db_*
containers of its instances). The worker reaches a node over SSH (Docker over ssh://, rsync of the workspace);
the web container through a filtering Docker proxy the panel starts on the node, listening on its private IP.
"""
import secrets

from django.core.validators import RegexValidator
from django.db import models

from .fields import EncryptedCharField

HOST_RE = r'^[A-Za-z0-9.-]{1,253}$'
SSH_USER_RE = r'^[a-z_][a-z0-9_-]{0,31}$'
WORKDIR_RE = r'^/[A-Za-z0-9._/-]{1,200}$'


def _new_token():
    return secrets.token_urlsafe(32)


class Server(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Sin preparar'
        READY = 'ready', 'Listo'
        ERROR = 'error', 'Error'

    name = models.CharField(max_length=50, unique=True,
                            validators=[RegexValidator(r'^[a-z0-9][a-z0-9-]{0,49}$', 'Minúsculas, números y guiones')])
    # The private IP (Hetzner network): SSH, the instances' ports and the Docker proxy all listen there
    host = models.CharField(max_length=253, unique=True, validators=[RegexValidator(HOST_RE, 'Una IP o un nombre de host')],
                            help_text='IP privada del servidor (red privada de Hetzner), p. ej. 10.0.0.3')
    ssh_user = models.CharField(max_length=32, default='root', validators=[RegexValidator(SSH_USER_RE, 'Usuario no válido')])
    ssh_port = models.PositiveIntegerField(default=22)
    workdir = models.CharField(max_length=200, default='/opt/community-sh-node',
                               validators=[RegexValidator(WORKDIR_RE, 'Ruta absoluta sin espacios')],
                               help_text='Carpeta del nodo con el código de sus instancias')
    # New instances can be created on it (an existing one keeps running either way)
    active = models.BooleanField(default=True, help_text='Admite instancias nuevas')
    notes = models.TextField(blank=True, default='')

    # Shared with the node's Docker proxy: other containers on the private network can't use it
    proxy_token = EncryptedCharField(max_length=64, default=_new_token)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    last_error = models.TextField(blank=True, default='')
    checked_at = models.DateTimeField(null=True, blank=True)
    # Filled in by the check (docker info / df)
    docker_version = models.CharField(max_length=50, blank=True, default='')
    cpus = models.PositiveSmallIntegerField(null=True, blank=True)
    memory_mb = models.PositiveIntegerField(null=True, blank=True)
    disk_total_gb = models.PositiveIntegerField(null=True, blank=True)
    disk_free_gb = models.PositiveIntegerField(null=True, blank=True)
    # Usage, read by the worker every few minutes (services/nodes.refresh_usage)
    memory_available_mb = models.PositiveIntegerField(null=True, blank=True)
    load_1m = models.FloatField(null=True, blank=True, help_text='Load average of the last minute')
    usage_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.host})'

    @property
    def ready(self):
        return self.status == self.Status.READY

    @staticmethod
    def _percent(used, total):
        return round(100 * used / total) if used is not None and total else None

    @property
    def memory_percent(self):
        if self.memory_available_mb is None or not self.memory_mb:
            return None
        return self._percent(self.memory_mb - self.memory_available_mb, self.memory_mb)

    @property
    def disk_percent(self):
        if self.disk_free_gb is None or not self.disk_total_gb:
            return None
        return self._percent(self.disk_total_gb - self.disk_free_gb, self.disk_total_gb)

    @property
    def cpu_percent(self):
        """Load of the last minute over its CPUs (100 %: every CPU busy)."""
        if self.load_1m is None or not self.cpus:
            return None
        return min(100, self._percent(self.load_1m, self.cpus))

    @property
    def usage_bars(self):
        """(label, percent, detail) for the Servers page."""
        bars = []
        if self.cpu_percent is not None:
            bars.append(('CPU', self.cpu_percent, f'{self.cpu_percent} % · carga {self.load_1m:.2f}'))
        if self.memory_percent is not None:
            used = (self.memory_mb - self.memory_available_mb) / 1024
            bars.append(('Memoria', self.memory_percent, f'{self.memory_percent} % · {used:.1f} de {self.memory_mb / 1024:.1f} GB'))
        if self.disk_percent is not None:
            bars.append(('Disco', self.disk_percent, f'{self.disk_percent} % · {self.disk_free_gb} GB libres de {self.disk_total_gb}'))
        return bars

    @property
    def reserved_memory_mb(self):
        """Memory the Odoo containers of its instances may take (their limits)."""
        return sum(self.instances.values_list('memory_limit_mb', flat=True))


class PanelKey(models.Model):
    """The public half of the worker's SSH key (the private one never leaves the worker's volume)."""
    public_key = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        key = cls.objects.order_by('-updated_at').first()
        return key.public_key if key else ''
