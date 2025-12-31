from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class Instance(models.Model):
    class Status(models.TextChoices):
        DEPLOYING = 'deploying', _('Deploying')
        RUNNING = 'running', _('Running')
        STOPPED = 'stopped', _('Stopped')
        ERROR = 'error', _('Error')

    name = models.CharField(max_length=100, unique=True, help_text="Subdomain name")
    odoo_version = models.CharField(max_length=10, choices=[
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
    ], default='17.0')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DEPLOYING)
    origin = models.CharField(max_length=50, blank=True, null=True, help_text="Origin of instance creation (manual, backup, duplicate)")
    
    # Github Integration
    github_repo = models.CharField(max_length=255, blank=True, null=True)
    github_branch = models.CharField(max_length=100, default='main')
    
    # Docker info
    container_id = models.CharField(max_length=100, blank=True, null=True)
    port = models.IntegerField(unique=True, null=True, blank=True)
    
    # Custom Domain & SSL
    custom_domain = models.CharField(max_length=255, blank=True, null=True, help_text="Custom domain (e.g., ejemplo.com)")
    ssl_enabled = models.BooleanField(default=False, help_text="SSL/HTTPS enabled")
    ssl_certificate_path = models.CharField(max_length=500, blank=True, null=True)
    ssl_key_path = models.CharField(max_length=500, blank=True, null=True)
    ssl_email = models.EmailField(blank=True, null=True, help_text="Email for Let's Encrypt notifications")
    
    # Database
    database_name = models.CharField(max_length=100, blank=True, null=True, help_text="Nombre de la base de datos de Odoo (dejar vacío para auto-detección)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.odoo_version})"

    @property
    def url(self):
        # Use custom domain if set, otherwise use localhost subdomain
        if self.custom_domain:
            protocol = "https" if self.ssl_enabled else "http"
            return f"{protocol}://{self.custom_domain}"
        return f"http://{self.name}.localhost"

# Import additional models
from .config_models import GitHubConfig
from .backup_models import Backup
from .blog_models import BlogPost

class UserProfile(models.Model):
    """Extended user profile with additional information"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, help_text="User avatar image")
    bio = models.TextField(blank=True, help_text="User biography")
    phone = models.CharField(max_length=20, blank=True, help_text="Phone number")
    
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
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if hasattr(instance, 'profile'):
        instance.profile.save()
