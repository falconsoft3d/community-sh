"""
Helpers de autorización: quién puede ver y operar cada recurso.

- Los superusuarios administran la plataforma y ven todo.
- El resto de usuarios solo ve sus propias instancias y backups.
"""
import re
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions


# Nombre de recurso: se usa en nombres de contenedores, redes, rutas de disco
# y labels de Traefik, así que solo admitimos minúsculas, números y guiones.
RESOURCE_NAME_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')
# Same rule Odoo's database manager enforces
DATABASE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$')
DOMAIN_RE = re.compile(r'^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')


def validate_resource_name(value):
    if not value or not RESOURCE_NAME_RE.match(value):
        raise ValidationError(
            'Solo se permiten letras minúsculas, números y guiones (sin empezar ni terminar en guion, máx. 63).'
        )


def validate_database_name(value):
    if value and not DATABASE_NAME_RE.match(value):
        raise ValidationError('Nombre de base de datos inválido (letras, números, "_", "." y "-").')


def validate_domain(value):
    if value and not DOMAIN_RE.match(value.lower()):
        raise ValidationError('Formato de dominio inválido.')


def get_global_config():
    """Configuración de la plataforma: la del primer superusuario."""
    from .config_models import GitHubConfig
    return GitHubConfig.objects.filter(user__is_superuser=True).order_by('id').first()


def is_registration_enabled():
    """El registro está cerrado por defecto, salvo para crear el primer usuario."""
    from django.contrib.auth.models import User
    if not User.objects.exists():
        return True
    config = get_global_config()
    return bool(config and config.registration_enabled)


def is_two_factor_required():
    config = get_global_config()
    return bool(config and config.two_factor_required)


def domain_in_use(domain, exclude_instance=None, exclude_container=None):
    """Evita que un usuario reclame el dominio del panel o de otro recurso."""
    from .container_models import Container
    from .models import Instance

    if not domain:
        return False
    domain = domain.lower()
    config = get_global_config()
    if config and config.main_domain and domain in (config.main_domain.lower(), f'www.{config.main_domain.lower()}'):
        return True

    instances = Instance.objects.filter(custom_domain__iexact=domain)
    if exclude_instance is not None:
        instances = instances.exclude(pk=exclude_instance.pk)
    containers = Container.objects.filter(custom_domain__iexact=domain)
    if exclude_container is not None:
        containers = containers.exclude(pk=exclude_container.pk)
    return instances.exists() or containers.exists()


def instances_for(user):
    from .models import Instance
    if user.is_superuser:
        return Instance.objects.all()
    return Instance.objects.filter(owner=user)


def projects_for(user):
    from .project_models import Project
    if user.is_superuser:
        return Project.objects.all()
    return Project.objects.filter(owner=user)


def get_project_for_user(user, pk):
    return get_object_or_404(projects_for(user), pk=pk)


def get_instance_for_user(user, pk):
    return get_object_or_404(instances_for(user), pk=pk)


def get_backup_for_user(user, backup_id):
    from .backup_models import Backup
    backups = Backup.objects.select_related('instance')
    if not user.is_superuser:
        backups = backups.filter(instance__owner=user)
    return get_object_or_404(backups, pk=backup_id)


# Brute-force protection for login and 2FA. Keyed by account, not IP: behind
# Traefik every request comes from the proxy address.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60


def is_locked_out(key):
    from django.core.cache import cache
    return cache.get(key, 0) >= MAX_ATTEMPTS


def register_failure(key):
    from django.core.cache import cache
    cache.add(key, 0, LOCKOUT_SECONDS)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, LOCKOUT_SECONDS)


def clear_failures(key):
    from django.core.cache import cache
    cache.delete(key)


def superuser_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


class IsOwnerOrSuperuser(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.is_superuser or obj.owner_id == request.user.id
