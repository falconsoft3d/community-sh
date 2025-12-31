# Services module
# Note: DockerService is in ../services.py, not in this package
# This package only contains template_loader for now

from .template_loader import get_template_loader, ContainerTemplateLoader

__all__ = ['get_template_loader', 'ContainerTemplateLoader']

