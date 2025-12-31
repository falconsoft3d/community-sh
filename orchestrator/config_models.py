from django.db import models
from django.contrib.auth.models import User

class GitHubConfig(models.Model):
    """Configuration for GitHub integration"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='github_config')
    personal_access_token = models.CharField(max_length=255, blank=True, help_text="GitHub Personal Access Token")
    default_organization = models.CharField(max_length=255, blank=True, help_text="Default GitHub organization")
    webhook_secret = models.CharField(max_length=255, blank=True, help_text="Webhook secret for GitHub")
    registration_enabled = models.BooleanField(default=True, help_text="Allow new user registrations")
    public_website_enabled = models.BooleanField(default=True, help_text="Enable public website and blog")
    two_factor_required = models.BooleanField(default=False, help_text="Require two-factor authentication for all users")
    
    # Domain and SSL configuration
    main_domain = models.CharField(max_length=255, blank=True, help_text="Main domain for the application (e.g., example.com)")
    ssl_enabled = models.BooleanField(default=False, help_text="Enable SSL/HTTPS for the domain")
    ssl_certificate_path = models.CharField(max_length=500, blank=True, help_text="Path to SSL certificate file")
    ssl_key_path = models.CharField(max_length=500, blank=True, help_text="Path to SSL private key file")
    
    # Email notifications
    email_notifications_enabled = models.BooleanField(default=False, help_text="Enable email notifications for instance operations")
    notification_emails = models.TextField(blank=True, help_text="Comma-separated list of emails to receive notifications")
    
    # Automatic backups configuration
    auto_backup_enabled = models.BooleanField(default=False, help_text="Enable automatic backups for all instances")
    auto_backup_frequency_unit = models.CharField(
        max_length=10, 
        default='day',
        choices=[('minute', 'Minutos'), ('hour', 'Horas'), ('day', 'Días'), ('week', 'Semanas')],
        help_text="Unit of time for backup frequency"
    )
    auto_backup_frequency_value = models.IntegerField(default=5, help_text="How often to run backups (e.g., every 5 days)")
    auto_backup_retention = models.IntegerField(default=5, help_text="Number of backups to keep. Older backups will be deleted automatically")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GitHub Config for {self.user.username}"
    
    class Meta:
        verbose_name = "GitHub Configuration"
        verbose_name_plural = "GitHub Configurations"
