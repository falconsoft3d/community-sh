# Services module
# Note: DockerService is in ../services.py, not in this package
# This package only contains template_loader for now

from .template_loader import get_template_loader, ContainerTemplateLoader

__all__ = ['get_template_loader', 'ContainerTemplateLoader']


def with_secrets(environment):
    """Environment with every "{secret}" value replaced by a new random key, so a template
    never ships a shared password. The values show on the container page."""
    import secrets
    return {key: secrets.token_hex(20) if value == '{secret}' else value
            for key, value in (environment or {}).items()}

