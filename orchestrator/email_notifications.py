from django.core.mail import send_mail
from django.conf import settings
from .config_models import GitHubConfig

def send_instance_notification(action, instance, user=None):
    """
    Send email notification for instance operations
    
    Args:
        action: 'created' or 'deleted'
        instance: Instance object
        user: User who performed the action
    """
    try:
        # Get first admin config for notification settings
        admin_config = GitHubConfig.objects.filter(user__is_superuser=True).first()
        
        if not admin_config or not admin_config.email_notifications_enabled:
            return
        
        if not admin_config.notification_emails:
            return
        
        # Parse email list
        recipient_list = [email.strip() for email in admin_config.notification_emails.split(',') if email.strip()]
        
        if not recipient_list:
            return
        
        # Prepare email content
        if action == 'created':
            subject = f'[Community SH] Nueva instancia creada: {instance.name}'
            message = f"""
Se ha creado una nueva instancia de Odoo:

Nombre: {instance.name}
Versión: {instance.odoo_version}
Estado: {instance.status}
Origen: {instance.origin or 'Manual'}
Puerto: {instance.port}
Repositorio: {instance.github_repo or 'N/A'}
Rama: {instance.github_branch or 'N/A'}
Usuario: {user.username if user else 'Sistema'}
Fecha: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}

URL: http://{instance.name}.localhost

---
Este es un mensaje automático de Community SH
"""
        elif action == 'deleted':
            subject = f'[Community SH] Instancia eliminada: {instance.name}'
            message = f"""
Se ha eliminado una instancia de Odoo:

Nombre: {instance.name}
Versión: {instance.odoo_version}
Origen: {instance.origin or 'Manual'}
Usuario: {user.username if user else 'Sistema'}
Fecha: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}

---
Este es un mensaje automático de Community SH
"""
        else:
            return
        
        # Send email
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,  # Don't raise errors if email fails
        )
        
        print(f"Email notification sent to {', '.join(recipient_list)}")
        
    except Exception as e:
        print(f"Error sending email notification: {str(e)}")
        # Don't raise exception, just log it
