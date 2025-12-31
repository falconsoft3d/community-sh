from django.db import models
from django.contrib.auth.models import User
import os
import socket

def get_template_choices():
    """Get template choices from YAML files"""
    try:
        from orchestrator.template_services import get_template_loader
        loader = get_template_loader()
        choices = loader.get_template_choices()
        return choices if choices else [('custom', 'Custom')]
    except Exception as e:
        print(f"Error loading template choices: {e}")
        return [('custom', 'Custom')]

class Container(models.Model):
    """Generic Docker container management"""
    
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
        ('creating', 'Creating'),
    ]
    
    name = models.CharField(max_length=255, unique=True)
    template = models.CharField(max_length=50, choices=get_template_choices, default='custom')
    image = models.CharField(max_length=255, help_text="Docker image (e.g., n8nio/n8n:latest)")
    port = models.IntegerField(help_text="Host port to expose")
    container_port = models.IntegerField(help_text="Container internal port")
    
    # Environment variables stored as JSON
    environment = models.JSONField(default=dict, blank=True, help_text="Environment variables")
    
    # Volumes
    volumes = models.JSONField(default=dict, blank=True, help_text="Volume mappings")
    
    # Network
    network = models.CharField(max_length=255, blank=True, default='bridge')

    # Command
    command = models.CharField(max_length=255, blank=True, null=True, help_text="Custom command to run")
    
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
        """Get the URL for this container"""
        # Use SERVER_IP from .env if available, otherwise default to 127.0.0.1
        server_ip = os.environ.get('SERVER_IP', '127.0.0.1')
        if not server_ip:
            server_ip = '127.0.0.1'
            
        # Handle IPv6 formatting (wrap in brackets for URL)
        display_ip = f"[{server_ip}]" if ":" in server_ip and "[" not in server_ip else server_ip
        
        return f"http://{display_ip}:{self.port}"
