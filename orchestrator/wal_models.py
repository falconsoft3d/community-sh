from django.db import models
from django.contrib.auth.models import User
from .models import Instance

class WALRestorePoint(models.Model):
    """Model to track WAL restore points for PITR"""
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name='wal_restore_points')
    name = models.CharField(max_length=255, help_text="Nombre descriptivo del punto de restauración")
    description = models.TextField(blank=True)
    
    # WAL Information
    wal_lsn = models.CharField(max_length=100, help_text="WAL Log Sequence Number (LSN)")
    wal_file = models.CharField(max_length=255, blank=True, help_text="WAL file name")
    timeline_id = models.IntegerField(default=1)
    
    # Point type
    restore_point_type = models.CharField(
        max_length=20,
        choices=[
            ('manual', 'Manual'),
            ('auto', 'Automático'),
            ('pre-deploy', 'Pre-Deploy'),
            ('scheduled', 'Programado'),
        ],
        default='manual'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Git information at this point
    git_commit = models.CharField(max_length=40, blank=True)
    git_branch = models.CharField(max_length=100, blank=True)
    
    # Status
    is_verified = models.BooleanField(default=False, help_text="Si el punto fue verificado")
    verification_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instance', '-created_at']),
            models.Index(fields=['instance', 'wal_lsn']),
        ]
    
    def __str__(self):
        return f"{self.instance.name} - {self.name} ({self.created_at})"


class WALArchive(models.Model):
    """Model to track WAL archive files"""
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name='wal_archives')
    wal_file_name = models.CharField(max_length=255, unique=True)
    file_path = models.CharField(max_length=512)
    file_size = models.BigIntegerField(help_text="Size in bytes")
    
    # WAL metadata
    timeline_id = models.IntegerField(default=1)
    start_lsn = models.CharField(max_length=100, blank=True)
    end_lsn = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    is_backed_up = models.BooleanField(default=False, help_text="Si fue copiado a backup remoto")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['instance', '-created_at']),
            models.Index(fields=['wal_file_name']),
        ]
    
    def __str__(self):
        return f"{self.instance.name} - {self.wal_file_name}"
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)


class PITRRestore(models.Model):
    """Model to track PITR restore operations"""
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name='pitr_restores')
    restore_target = models.DateTimeField(help_text="Target timestamp for restoration")
    target_lsn = models.CharField(max_length=100, blank=True, help_text="Target LSN if specified")
    
    # Restore point reference
    restore_point = models.ForeignKey(WALRestorePoint, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pendiente'),
            ('in_progress', 'En Progreso'),
            ('completed', 'Completado'),
            ('failed', 'Fallido'),
        ],
        default='pending'
    )
    
    error_message = models.TextField(blank=True)
    
    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # User tracking
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Recovery details
    recovery_logs = models.TextField(blank=True)
    wal_files_replayed = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['instance', '-started_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.instance.name} - PITR to {self.restore_target} [{self.status}]"
