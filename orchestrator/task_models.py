from django.db import models
from django.contrib.auth.models import User


class Task(models.Model):
    """Long-running operation queued for the worker (manage.py run_worker)."""

    class Kind(models.TextChoices):
        DEPLOY = 'deploy', 'Desplegar'
        DUPLICATE = 'duplicate', 'Duplicar'
        RENAME = 'rename', 'Renombrar'
        BACKUP = 'backup', 'Respaldo'
        RESTORE = 'restore', 'Restaurar'
        CREATE_FROM_BACKUP = 'create_from_backup', 'Crear desde respaldo'
        BACKUP_ALL = 'backup_all', 'Respaldar todas'
        INSTALL_MODULE = 'install_module', 'Instalar módulo'
        PULL_IMAGE = 'pull_image', 'Descargar imagen'
        AI_MODULE = 'ai_module', 'Instalar módulo (IA)'
        DELETE_PROJECT = 'delete_project', 'Eliminar proyecto'
        AI_CHAT = 'ai_chat', 'Asistente de IA'
        ODOO_MIGRATION = 'odoo_migration', 'Migrar desde otro Odoo'

    class Status(models.TextChoices):
        PENDING = 'pending', 'En cola'
        RUNNING = 'running', 'En curso'
        DONE = 'done', 'Completada'
        FAILED = 'failed', 'Fallida'

    kind = models.CharField(max_length=30, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    instance = models.ForeignKey('Instance', on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    params = models.JSONField(default=dict, blank=True)
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in (self.Status.PENDING, self.Status.RUNNING)
