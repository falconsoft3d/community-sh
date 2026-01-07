"""
Middleware para manejar redirecciones SSL/HTTPS de manera condicional
"""
from django.conf import settings
from django.http import HttpResponsePermanentRedirect, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin


class ConditionalSSLRedirectMiddleware(MiddlewareMixin):
    """
    Middleware que fuerza HTTPS o HTTP basándose en la configuración ENABLE_SSL
    
    - Si ENABLE_SSL=True: Redirige todas las peticiones HTTP a HTTPS
    - Si ENABLE_SSL=False: Permite HTTP normalmente
    """
    
    def process_request(self, request):
        # Solo aplicar en producción (DEBUG=False)
        if settings.DEBUG:
            return None
        
        # Verificar si SSL está habilitado
        enable_ssl = getattr(settings, 'ENABLE_SSL', False)
        
        # Si SSL está habilitado y la petición no es segura, redirigir a HTTPS
        if enable_ssl and not request.is_secure():
            # Excluir rutas específicas si es necesario (por ejemplo, health checks)
            excluded_paths = getattr(settings, 'SSL_REDIRECT_EXEMPT', [])
            if request.path not in excluded_paths:
                # Construir URL HTTPS
                url = request.build_absolute_uri(request.get_full_path())
                secure_url = url.replace('http://', 'https://', 1)
                return HttpResponsePermanentRedirect(secure_url)
        
        # Si SSL está deshabilitado y la petición es segura, redirigir a HTTP
        # (Esto es útil en desarrollo o cuando se desactiva SSL temporalmente)
        if not enable_ssl and request.is_secure():
            # Solo hacer esto si la configuración lo permite explícitamente
            force_http = getattr(settings, 'FORCE_HTTP_WHEN_SSL_DISABLED', False)
            if force_http:
                url = request.build_absolute_uri(request.get_full_path())
                insecure_url = url.replace('https://', 'http://', 1)
                return HttpResponsePermanentRedirect(insecure_url)
        
        return None


class DynamicAllowedHostsMiddleware(MiddlewareMixin):
    """
    Middleware que valida ALLOWED_HOSTS dinámicamente usando el dominio principal
    configurado en GitHubConfig
    """
    
    def process_request(self, request):
        # En desarrollo, permitir todos los hosts
        if settings.DEBUG:
            return None
        
        # Obtener el host de la petición
        host = request.get_host().split(':')[0]
        
        # Lista de hosts permitidos por defecto
        allowed_hosts = list(settings.ALLOWED_HOSTS) if settings.ALLOWED_HOSTS != ['*'] else []
        
        # Agregar localhost y community.local siempre
        default_hosts = ['localhost', '127.0.0.1', 'community.local']
        allowed_hosts.extend(default_hosts)
        
        # Intentar obtener el dominio principal desde la configuración
        try:
            from orchestrator.config_models import GitHubConfig
            
            # Obtener el primer config (en un sistema multiusuario, esto debería ajustarse)
            config = GitHubConfig.objects.first()
            
            if config and config.main_domain:
                # Agregar el dominio principal y su variante con www
                allowed_hosts.append(config.main_domain)
                allowed_hosts.append(f'www.{config.main_domain}')
        except Exception:
            # Si hay algún error (por ejemplo, la DB no está lista), continuar
            pass
        
        # Verificar si el host actual está en la lista de hosts permitidos
        if host not in allowed_hosts and settings.ALLOWED_HOSTS != ['*']:
            return HttpResponseForbidden(f'Host "{host}" no permitido. Configure el dominio en Settings.')
        
        return None
