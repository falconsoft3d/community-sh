from django.db import models
from django.contrib.auth.models import User

class Container(models.Model):
    """Generic Docker container management"""
    
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
        ('creating', 'Creating'),
    ]
    
    TEMPLATE_CHOICES = [
        ('custom', 'Custom'),
        ('n8n', 'n8n - Workflow Automation'),
        ('pgadmin', 'pgAdmin - PostgreSQL Admin'),
        ('portainer', 'Portainer - Docker Management'),
        ('redis', 'Redis - Cache Database'),
        ('mongodb', 'MongoDB - NoSQL Database'),
    ]
    
    name = models.CharField(max_length=255, unique=True)
    template = models.CharField(max_length=50, choices=TEMPLATE_CHOICES, default='custom')
    image = models.CharField(max_length=255, help_text="Docker image (e.g., n8nio/n8n:latest)")
    port = models.IntegerField(help_text="Host port to expose")
    container_port = models.IntegerField(help_text="Container internal port")
    
    # Environment variables stored as JSON
    environment = models.JSONField(default=dict, blank=True, help_text="Environment variables")
    
    # Volumes
    volumes = models.JSONField(default=dict, blank=True, help_text="Volume mappings")
    
    # Network
    network = models.CharField(max_length=255, blank=True, default='bridge')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='stopped')
    container_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Metadata
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='containers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Container'
        verbose_name_plural = 'Containers'
    
    def __str__(self):
        return f"{self.name} ({self.template})"
    
    @property
    def url(self):
        """Get the Traefik URL for this container"""
        return f"http://{self.name}.localhost"
