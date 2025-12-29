from django.db import models
from django.contrib.auth.models import User

class Backup(models.Model):
    """Model to track instance backups"""
    instance = models.ForeignKey('Instance', on_delete=models.CASCADE, related_name='backups')
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512)
    include_filestore = models.BooleanField(default=True)
    file_size = models.BigIntegerField(help_text="Size in bytes")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.instance.name} - {self.filename}"
    
    @property
    def file_size_mb(self):
        return round(self.file_size / (1024 * 1024), 2)
