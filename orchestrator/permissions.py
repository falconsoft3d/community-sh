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
# Git branches: never starting with "-" (git would read it as an option) and without ".."
GIT_BRANCH_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9._/-]{0,99}$')
# Only HTTPS clone URLs (no ssh://, file://, ext:: or values that look like options)
REPO_URL_RE = re.compile(r'^https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+?(\.git)?$')


def validate_resource_name(value):
    if not value or not RESOURCE_NAME_RE.match(value):
        raise ValidationError(
            'Solo se permiten letras minúsculas, números y guiones (sin empezar ni terminar en guion, máx. 63).'
        )


def validate_git_branch(value):
    if value and (not GIT_BRANCH_RE.match(value) or '..' in value or value.endswith(('/', '.lock'))):
        raise ValidationError('Rama inválida: letras, números, «.», «_», «-» y «/», sin empezar por guion.')


def validate_repo_url(value):
    if value and (not REPO_URL_RE.match(value) or '..' in value):
        raise ValidationError('URL inválida: usa la URL HTTPS de clonado (p. ej. https://github.com/OCA/web.git).')


def client_ip(request):
    """
    The address of the visitor. Behind Traefik the connection comes from a private (Docker)
    address and Traefik appends the real one as the LAST X-Forwarded-For entry; the entries
    before it are whatever the client sent, so they are never trusted. A direct connection
    (public address) is taken as is, whatever headers it carries.
    """
    import ipaddress
    remote = request.META.get('REMOTE_ADDR', '')
    try:
        proxied = ipaddress.ip_address(remote).is_private or ipaddress.ip_address(remote).is_loopback
    except ValueError:
        proxied = False
    if proxied:
        forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded[-1]))
            except ValueError:
                pass
    return remote or None


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
    domain = domain.lower().rstrip('.')
    config = get_global_config()
    if config and config.main_domain and domain in (config.main_domain.lower(), f'www.{config.main_domain.lower()}'):
        return True
    # The automatic subdomains of the platform (<subdomain>.<domain>) belong to their instance or container
    from .services.domains import main_domain
    platform = main_domain()
    if platform and domain in (platform, f'www.{platform}'):
        return True
    if platform and domain.endswith(f'.{platform}'):
        label = domain[:-len(platform) - 1].removeprefix('www.')
        owners = Instance.objects.filter(subdomain=label)
        if exclude_instance is not None:
            owners = owners.exclude(pk=exclude_instance.pk)
        named = Container.objects.filter(name=label)
        if exclude_container is not None:
            named = named.exclude(pk=exclude_container.pk)
        if owners.exists() or named.exists():
            return True

    instances = Instance.objects.filter(custom_domain__iexact=domain)
    if exclude_instance is not None:
        instances = instances.exclude(pk=exclude_instance.pk)
    containers = Container.objects.filter(custom_domain__iexact=domain)
    if exclude_container is not None:
        containers = containers.exclude(pk=exclude_container.pk)
    return instances.exists() or containers.exists()


def is_client(user):
    profile = getattr(user, 'profile', None)
    return bool(user.is_authenticated and not user.is_superuser and profile and profile.is_client)


def can_manage(user, obj):
    """Owners and superusers manage; clients only see and operate (start, deploy, backups)."""
    return user.is_superuser or obj.owner_id == user.id


def instances_for(user):
    """Instances a user can see: their own, and as a client those of their projects."""
    from django.db.models import Q
    from .models import Instance
    if user.is_superuser:
        return Instance.objects.all()
    return Instance.objects.filter(Q(owner=user) | Q(project__client=user))


def projects_for(user):
    from django.db.models import Q
    from .project_models import Project
    if user.is_superuser:
        return Project.objects.all()
    return Project.objects.filter(Q(owner=user) | Q(client=user))


def managed_projects_for(user):
    """Projects a user can put instances in (clients only operate theirs)."""
    from .project_models import Project
    return Project.objects.all() if user.is_superuser else Project.objects.filter(owner=user)


def get_project_for_user(user, pk, manage=False):
    project = get_object_or_404(projects_for(user), pk=pk)
    if manage and not can_manage(user, project):
        raise PermissionDenied
    return project


def get_instance_for_user(user, pk, manage=False):
    instance = get_object_or_404(instances_for(user), pk=pk)
    if manage and not can_manage(user, instance):
        raise PermissionDenied
    return instance


def get_backup_for_user(user, backup_id, manage=False):
    from django.db.models import Q
    from .backup_models import Backup
    backups = Backup.objects.select_related('instance')
    if not user.is_superuser:
        backups = backups.filter(Q(instance__owner=user) | Q(instance__project__client=user))
    backup = get_object_or_404(backups, pk=backup_id)
    if manage and not can_manage(user, backup.instance):
        raise PermissionDenied
    return backup


def management_required(view_func):
    """Views that create things (projects, instances, containers): not for clients."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if is_client(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


# Brute-force protection for login and 2FA: 5 failures from one address lock that address out of
# the account; 20 from anywhere lock the account itself (so one attacker can't lock its owner out).
MAX_ATTEMPTS = 5
MAX_ACCOUNT_ATTEMPTS = 20
LOCKOUT_SECONDS = 15 * 60


def is_locked_out(key, limit=MAX_ATTEMPTS):
    from django.core.cache import cache
    return cache.get(key, 0) >= limit


def login_lockout_keys(request, username):
    """(per address, per account) keys. The username as Django authenticates it (NFKC, any case)."""
    import unicodedata
    account = unicodedata.normalize('NFKC', username or '').strip().casefold()
    return f'login-fail:{account}:{client_ip(request)}', f'login-fail:{account}'


def missing_required_2fa(user):
    """2FA is mandatory on the platform and this user hasn't set it up."""
    if not is_two_factor_required():
        return False
    profile = getattr(user, 'profile', None)
    return not (profile and profile.two_factor_enabled and profile.two_factor_secret)


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
    """Clients may read and run the operate actions; everything else needs the owner."""
    CLIENT_ACTIONS = ('deploy', 'stop', 'restart', 'backup')

    def has_permission(self, request, view):
        if getattr(view, 'action', None) == 'create':
            return not is_client(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if can_manage(request.user, obj):
            return True
        return request.method in permissions.SAFE_METHODS or getattr(view, 'action', None) in self.CLIENT_ACTIONS
