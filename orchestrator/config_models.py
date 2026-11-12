from django.db import models
from django.contrib.auth.models import User

class GitHubConfig(models.Model):
    """Configuration for GitHub integration"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='github_config')
    personal_access_token = models.CharField(max_length=255, blank=True, help_text="GitHub Personal Access Token")
    default_organization = models.CharField(max_length=255, blank=True, help_text="Default GitHub organization")
    webhook_secret = models.CharField(max_length=255, blank=True, help_text="Webhook secret for GitHub")
    registration_enabled = models.BooleanField(default=False, help_text="Allow new user registrations")
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
    # Alerts: failed tasks, instances that stop answering, full disk or memory, missing certificates
    alerts_enabled = models.BooleanField(default=True, help_text="Send alerts by email (and to the webhook)")
    alert_webhook_url = models.URLField(blank=True, help_text="Optional: Slack, Discord, Google Chat, n8n... receives each alert as JSON")
    
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
    # MCP server for Claude (Claude Code, Claude Desktop...)
    mcp_enabled = models.BooleanField(default=False, help_text="Expose the MCP server at /mcp/")
    
    # AI assistant (OpenAI / ChatGPT)
    ai_enabled = models.BooleanField(default=False, help_text="Enable the AI assistant in instances")
    openai_api_key = models.CharField(max_length=255, blank=True, help_text="OpenAI API key")
    openai_model = models.CharField(max_length=100, blank=True, help_text="OpenAI model used by the assistant")
    ai_instructions = models.TextField(blank=True, help_text="Extra instructions added to the assistant's system prompt")
    
    # Outgoing mail server (SMTP): notifications and the credentials of the demos
    smtp_enabled = models.BooleanField(default=False, help_text="Send emails through this SMTP server")
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_security = models.CharField(max_length=10, default='starttls',
                                     choices=[('starttls', 'STARTTLS'), ('ssl', 'SSL/TLS'), ('none', 'Ninguna')])
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = models.CharField(max_length=255, blank=True)
    smtp_from_email = models.EmailField(blank=True, help_text="Sender address")
    smtp_from_name = models.CharField(max_length=100, blank=True, default='Community SH')

    # Demos (test mode of the projects), for the whole server: a cap against abuse and memory use
    trial_max_per_day = models.PositiveIntegerField(default=10, help_text="Demos that can be created per day (all projects)")
    trial_max_active_total = models.PositiveIntegerField(default=4, help_text="Demos running at once on the server")

    # Copy of every backup off the server, in an S3-compatible bucket (AWS, Backblaze B2, Cloudflare R2, Wasabi, MinIO...)
    offsite_enabled = models.BooleanField(default=False, help_text="Copy every backup to the S3 bucket")
    s3_endpoint_url = models.URLField(blank=True, help_text="Empty for AWS; e.g. https://s3.eu-central-003.backblazeb2.com")
    s3_region = models.CharField(max_length=50, blank=True)
    s3_bucket = models.CharField(max_length=255, blank=True)
    s3_access_key = models.CharField(max_length=255, blank=True)
    s3_secret_key = models.CharField(max_length=255, blank=True)
    s3_prefix = models.CharField(max_length=255, blank=True, default='community-sh')
    offsite_retention_days = models.PositiveIntegerField(default=30, help_text="Copies older than this are deleted from the bucket (0: kept)")

    last_auto_backup_at = models.DateTimeField(null=True, blank=True, help_text="When the last automatic backup run started")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GitHub Config for {self.user.username}"
    
    class Meta:
        verbose_name = "GitHub Configuration"
        verbose_name_plural = "GitHub Configurations"
