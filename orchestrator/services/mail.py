"""
Outgoing mail through the SMTP server of Settings → Email. Without it (or switched off) nothing is
sent: the panel's default backend only prints to the console.
"""
import logging

from django.core.mail import EmailMultiAlternatives, get_connection

logger = logging.getLogger(__name__)


def smtp_config():
    """The platform config when its SMTP server is switched on and complete, else None."""
    from ..permissions import get_global_config
    config = get_global_config()
    if not config or not config.smtp_enabled or not config.smtp_host or not config.smtp_from_email:
        return None
    return config


def connection(host, port, security, username='', password='', timeout=15):
    return get_connection('django.core.mail.backends.smtp.EmailBackend', host=host, port=int(port),
                          username=username or None, password=password or None,
                          use_tls=security == 'starttls', use_ssl=security == 'ssl', timeout=timeout, fail_silently=False)


def sender(config):
    return f'{config.smtp_from_name} <{config.smtp_from_email}>' if config.smtp_from_name else config.smtp_from_email


def send(subject, body, to, html=None, config=None):
    """Send one email. Returns (sent, error): (False, '') when there is no SMTP server configured."""
    config = config or smtp_config()
    if config is None:
        return False, ''
    recipients = [to] if isinstance(to, str) else list(to)
    try:
        message = EmailMultiAlternatives(subject, body, sender(config), recipients, connection=connection(
            config.smtp_host, config.smtp_port, config.smtp_security, config.smtp_username, config.smtp_password))
        if html:
            message.attach_alternative(html, 'text/html')
        message.send()
        return True, ''
    except Exception as e:
        logger.warning('Email to %s failed: %s', recipients, e)
        return False, str(e)
