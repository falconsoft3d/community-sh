"""
Audit log: record(request, action, target, details). Actions are short codes shown with their label on the
Auditoría page; add new ones to ACTIONS.
"""
import logging

logger = logging.getLogger(__name__)

ACTIONS = {
    'login': 'Inicio de sesión',
    'login_failed': 'Inicio de sesión fallido',
    'logout': 'Cierre de sesión',
    'secret_master_password': 'Ver/copiar Master Password',
    'secret_admin_password': 'Ver/copiar contraseña del administrador',
    'admin_login': 'Entrar como admin en Odoo',
    'reset_admin_password': 'Restablecer contraseña del administrador',
    'settings': 'Cambiar la configuración',
    'token_created': 'Crear token',
    'token_revoked': 'Revocar token',
    'user_created': 'Crear usuario',
    'user_edited': 'Editar usuario',
    'user_deleted': 'Eliminar usuario',
    'instance_deleted': 'Eliminar instancia',
    'instance_renamed': 'Renombrar instancia',
    'instance_moved': 'Mover instancia',
    'instance_memory': 'Cambiar límite de memoria',
    'instance_env_vars': 'Cambiar variables de entorno',
    'offsite_restore': 'Restaurar desde S3',
    'refresh_data': 'Refrescar datos desde otra instancia',
    'instance_power': 'Cambiar el ahorro de memoria',
    'instance_deploy': 'Desplegar',
    'instance_restart': 'Reiniciar',
    'instance_stop': 'Detener',
    'backup_created': 'Crear backup',
    'backup_downloaded': 'Descargar backup',
    'backup_restored': 'Restaurar backup',
    'backups_verify': 'Comprobar backups',
    'db_manager': 'Abrir/cerrar el gestor de bases de datos de Odoo',
    'reauth': 'Confirmar la contraseña',
    'reauth_failed': 'Confirmación de contraseña fallida',
}


def record(request, action, target='', details='', user=None):
    """Never raises: auditing must not break what it records."""
    from .audit_models import AuditEvent
    from .permissions import client_ip
    try:
        user = user or (getattr(request, 'user', None) if request is not None else None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None
        AuditEvent.objects.create(
            user=user, username=(user.get_username() if user else '')[:150], action=action,
            target=str(target or '')[:255], details=str(details or '')[:2000],
            ip=client_ip(request) if request is not None else None,
        )
    except Exception:
        logger.exception('Audit %s failed', action)
