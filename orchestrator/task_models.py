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
        INSTALL_BROWSER = 'install_browser', 'Instalar navegador'

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
    # Kept up to date while it runs (orchestrator.task_log): what the worker printed and logged, the bar and its step
    log = models.TextField(blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    step = models.CharField(max_length=255, blank=True)
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

    @property
    def duration(self):
        """Seconds it took, or has been running; None while it waits in the queue."""
        if not self.started_at:
            return None
        from django.utils import timezone
        return int(((self.finished_at or timezone.now()) - self.started_at).total_seconds())

    @property
    def duration_display(self):
        seconds = self.duration
        if seconds is None:
            return ''
        if seconds < 60:
            return f'{seconds} s'
        if seconds < 3600:
            return f'{seconds // 60} min {seconds % 60:02d} s'
        return f'{seconds // 3600} h {seconds % 3600 // 60:02d} min'

    @property
    def bar_percent(self):
        """What the bar shows: full once it finished, whatever the last step said."""
        return 100 if self.status in (self.Status.DONE, self.Status.FAILED) else self.progress
