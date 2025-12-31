"""
Middleware para manejar redirecciones SSL/HTTPS de manera condicional
"""
from django.conf import settings
from django.http import HttpResponsePermanentRedirect
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
