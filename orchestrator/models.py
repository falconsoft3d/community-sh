from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
import os
import secrets
import socket
from django.db.models.signals import post_save
from django.dispatch import receiver
from .permissions import validate_resource_name, validate_domain, validate_database_name, validate_git_branch, validate_repo_url
from .instance_env import validate_env_vars

MEMORY_LIMIT_MIN_MB, MEMORY_LIMIT_MAX_MB = 256, 32768


def validate_memory_limit(value):
    from django.core.exceptions import ValidationError
    if value and not MEMORY_LIMIT_MIN_MB <= value <= MEMORY_LIMIT_MAX_MB:
        raise ValidationError(f'Entre {MEMORY_LIMIT_MIN_MB} y {MEMORY_LIMIT_MAX_MB} MB, o 0 para no limitar')


def generate_master_password():
    return secrets.token_urlsafe(18)


def generate_webhook_secret():
    return secrets.token_hex(24)

class Instance(models.Model):
    class Status(models.TextChoices):
        DEPLOYING = 'deploying', _('Deploying')
        RUNNING = 'running', _('Running')
        STOPPED = 'stopped', _('Stopped')
        ERROR = 'error', _('Error')

    name = models.CharField(max_length=100, unique=True, validators=[validate_resource_name], help_text="Subdomain name")
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='instances')
    project = models.ForeignKey('Project', on_delete=models.PROTECT, null=True, blank=True, related_name='instances')
    odoo_version = models.CharField(max_length=10, choices=[
        ('8.0', '8.0'),
        ('9.0', '9.0'),
        ('10.0', '10.0'),
        ('11.0', '11.0'),
        ('12.0', '12.0'),
        ('13.0', '13.0'),
        ('14.0', '14.0'),
        ('15.0', '15.0'),
        ('16.0', '16.0'),
        ('17.0', '17.0'),
        ('18.0', '18.0'),
        ('19.0', '19.0'),
        ('20.0', '20.0'),
    ], default='17.0')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DEPLOYING)
    origin = models.CharField(max_length=50, blank=True, null=True, help_text="Origin of instance creation (manual, backup, duplicate)")
    
    # Github Integration
    github_repo = models.CharField(max_length=255, blank=True, null=True, validators=[validate_repo_url])
    github_branch = models.CharField(max_length=100, default='main', validators=[validate_git_branch])
    
    # Docker info
    container_id = models.CharField(max_length=100, blank=True, null=True)
    data_volume = models.CharField(max_length=255, blank=True, default='', help_text="Docker volume holding /var/lib/odoo (filestore)")
    master_password = models.CharField(max_length=64, default=generate_master_password, help_text="Odoo master password (database manager)")
    # Cap of the Odoo container: one runaway instance can't take the memory of the server (and of the others)
    memory_limit_mb = models.PositiveIntegerField(default=1536, validators=[validate_memory_limit], help_text="Memory limit of the Odoo container in MB (0: no limit)")

    # The administrator the panel created (database created from the panel/API/MCP, demo), shown to who manages it
    admin_login = models.CharField(max_length=100, blank=True, default='', help_text="Login of the administrator the panel created")
    admin_password = models.CharField(max_length=64, blank=True, default='', help_text="Password of the administrator the panel created")
    admin_database = models.CharField(max_length=100, blank=True, default='', help_text="Database of that administrator")
    port = models.IntegerField(unique=True, null=True, blank=True)
    
    # Custom Domain & SSL
    custom_domain = models.CharField(max_length=255, blank=True, null=True, validators=[validate_domain], help_text="Custom domain (e.g., ejemplo.com)")
    ssl_enabled = models.BooleanField(default=False, help_text="SSL/HTTPS enabled")
    browser = models.BooleanField(default=False, help_text="Google Chrome in the Odoo container (WhatsApp Web...): installed again on every deploy")
    ssl_certificate_path = models.CharField(max_length=500, blank=True, null=True)
    ssl_key_path = models.CharField(max_length=500, blank=True, null=True)
    ssl_email = models.EmailField(blank=True, null=True, help_text="Email for Let's Encrypt notifications")
    subdomain = models.CharField(max_length=63, blank=True, default='', validators=[validate_resource_name], help_text="Subdomain under the platform domain (client-version-name)")
    
    # Database
    database_name = models.CharField(max_length=100, blank=True, null=True, validators=[validate_database_name], help_text="Nombre de la base de datos de Odoo (dejar vacío para auto-detección)")
    
    # Demos: several databases in one instance (and one certificate), opened with https://host/?name
    demo_default_db = models.CharField(max_length=100, blank=True, default='', validators=[validate_database_name],
                                       help_text="Odoo 18+: database opened without ?name. Empty: a normal instance.")

    # A push to one of its repositories (GitHub webhook) updates the instance on its own
    class AutoUpdate(models.TextChoices):
        OFF = '', 'Desactivada'
        PULL = 'pull', 'Pull y reiniciar Odoo'
        UPDATE_ALL = 'update', 'Pull y actualizar todos los módulos (-u all)'

    # On by default (pull): a push, and the daily pass, keep every instance on the last commit of its branches
    auto_update = models.CharField(max_length=10, choices=AutoUpdate.choices, default=AutoUpdate.PULL, blank=True)
    webhook_secret = models.CharField(max_length=64, default=generate_webhook_secret,
                                      help_text="Signs the GitHub webhook calls of this instance")

    # Shown next to the instance on the demo page of its project (test mode) and in the public API
    description = models.TextField(blank=True, default='', help_text="Public description for the demo page")

    # Environment variables of the Odoo container (NAME=value per line), applied on every deploy
    env_vars = models.TextField(blank=True, default='', validators=[validate_env_vars],
                                help_text="Environment variables of the Odoo container: NAME=value, one per line")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.odoo_version})"

    def save(self, *args, **kwargs):
        from .services.domains import build_subdomain
        if not self.subdomain:
            self.subdomain = build_subdomain(self)
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = {*kwargs['update_fields'], 'subdomain'}
        super().save(*args, **kwargs)

    @property
    def url(self):
        """Get the primary URL for accessing this instance"""
        from .services.domains import acme_enabled, main_domain
        # Use custom domain if set
        if self.custom_domain:
            protocol = "https" if self.ssl_enabled or acme_enabled() else "http"
            return f"{protocol}://{self.custom_domain}"

        # Then its subdomain under the platform domain
        domain = main_domain()
        if domain and self.subdomain:
            return f"{'https' if acme_enabled() else 'http'}://{self.subdomain}.{domain}"
        
        # Use SERVER_IP from .env if available, otherwise default to 127.0.0.1
        server_ip = os.environ.get('SERVER_IP', '127.0.0.1')
        if not server_ip:
            server_ip = '127.0.0.1'
        
        # Handle IPv6 formatting (wrap in brackets for URL)
        display_ip = f"[{server_ip}]" if ":" in server_ip and "[" not in server_ip else server_ip
        
        # Get port from container if exists
        uri = f"http://{display_ip}"
        
        # If we have a mapped port, use it
        if self.port:
            return f"{uri}:{self.port}"
            
        return uri
    
    @property
    def port_is_public(self):
        """Its port answers from outside (no domain with HTTPS): the IP:port address works."""
        from .services.docker_service import published_ip
        return published_ip() != '127.0.0.1'

    @property
    def url_with_port(self):
        """Get the URL with IP and port (used as alternative URL)"""
        server_ip = os.environ.get('SERVER_IP', '127.0.0.1')
        if not server_ip:
            server_ip = '127.0.0.1'
        
        # Handle IPv6 formatting (wrap in brackets for URL)
        display_ip = f"[{server_ip}]" if ":" in server_ip and "[" not in server_ip else server_ip
        
        # Get port from container if exists
        uri = f"http://{display_ip}"
        
        # If we have a mapped port, use it
        if self.port:
            return f"{uri}:{self.port}"
            
        return uri

# Import additional models
from .config_models import GitHubConfig
from .backup_models import Backup
from .blog_models import BlogPost
from .task_models import Task
from .project_models import Project, ProjectTag
from .trial_models import TrialRequest
from .contact_models import Contact
from .ai_models import AIAttachment, AIFileChange, AIMessage
from .repository_models import InstanceRepository
from .mcp_models import MCPToken
from .todo_models import Todo
from .metrics_models import MetricRollup, MetricSample

class UserProfile(models.Model):
    """Extended user profile with additional information"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, help_text="User avatar image")
    bio = models.TextField(blank=True, help_text="User biography")
    phone = models.CharField(max_length=20, blank=True, help_text="Phone number")
    
    # Clients log in to see and operate the instances of their projects
    is_client = models.BooleanField(default=False, help_text="Client account: sees and operates only its projects")
    company = models.CharField(max_length=150, blank=True, help_text="Client company name")
    
    # Two-Factor Authentication
    two_factor_enabled = models.BooleanField(default=False, help_text="Enable two-factor authentication")
    two_factor_secret = models.CharField(max_length=32, blank=True, help_text="TOTP secret key")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile for {self.user.username}"
    
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile when User is created"""
    # raw=True while loading fixtures: the profile comes from the fixture itself
    if created and not kwargs.get('raw'):
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if not kwargs.get('raw') and hasattr(instance, 'profile'):
        instance.profile.save()
