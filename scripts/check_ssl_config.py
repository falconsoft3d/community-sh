#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de verificación de configuración SSL/HTTPS
Comprueba que las configuraciones de SSL están correctamente aplicadas
"""

import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings


def check_ssl_configuration():
    """Verifica la configuración SSL/HTTPS actual"""
    
    print("=" * 70)
    print("VERIFICACIÓN DE CONFIGURACIÓN SSL/HTTPS")
    print("=" * 70)
    print()
    
    # Variables de entorno
    print("📋 Variables de Entorno:")
    print(f"  - DEBUG: {settings.DEBUG}")
    print(f"  - ENABLE_SSL: {settings.ENABLE_SSL}")
    print()
    
    # Configuraciones de seguridad
    print("🔒 Configuraciones de Seguridad:")
    
    if settings.DEBUG:
        print("  ⚠️  DEBUG está habilitado - Configuraciones SSL ignoradas")
        print("  ℹ️  En desarrollo, tanto HTTP como HTTPS están permitidos")
    else:
        print("  ✓ DEBUG está deshabilitado - Configuraciones SSL activas")
        
        if settings.ENABLE_SSL:
            print()
            print("  🔐 SSL/HTTPS HABILITADO:")
            print(f"    - SECURE_SSL_REDIRECT: {getattr(settings, 'SECURE_SSL_REDIRECT', False)}")
            print(f"    - SESSION_COOKIE_SECURE: {getattr(settings, 'SESSION_COOKIE_SECURE', False)}")
            print(f"    - CSRF_COOKIE_SECURE: {getattr(settings, 'CSRF_COOKIE_SECURE', False)}")
            print(f"    - SECURE_HSTS_SECONDS: {getattr(settings, 'SECURE_HSTS_SECONDS', 0)}")
            print(f"    - SECURE_HSTS_INCLUDE_SUBDOMAINS: {getattr(settings, 'SECURE_HSTS_INCLUDE_SUBDOMAINS', False)}")
            print(f"    - SECURE_HSTS_PRELOAD: {getattr(settings, 'SECURE_HSTS_PRELOAD', False)}")
            print()
            print("  ✅ Resultado: HTTP será redirigido a HTTPS automáticamente")
        else:
            print()
            print("  🌐 SSL/HTTPS DESHABILITADO:")
            print(f"    - SECURE_SSL_REDIRECT: {getattr(settings, 'SECURE_SSL_REDIRECT', True)}")
            print(f"    - SESSION_COOKIE_SECURE: {getattr(settings, 'SESSION_COOKIE_SECURE', True)}")
            print(f"    - CSRF_COOKIE_SECURE: {getattr(settings, 'CSRF_COOKIE_SECURE', True)}")
            print()
            print("  ✅ Resultado: HTTP está permitido sin redirecciones")
        
        print()
        print("  🛡️  Configuraciones de Seguridad Generales:")
        print(f"    - SECURE_BROWSER_XSS_FILTER: {getattr(settings, 'SECURE_BROWSER_XSS_FILTER', False)}")
        print(f"    - SECURE_CONTENT_TYPE_NOSNIFF: {getattr(settings, 'SECURE_CONTENT_TYPE_NOSNIFF', False)}")
        print(f"    - X_FRAME_OPTIONS: {getattr(settings, 'X_FRAME_OPTIONS', 'SAMEORIGIN')}")
    
    print()
    print("🎯 Configuraciones Adicionales:")
    ssl_exempt = settings.SSL_REDIRECT_EXEMPT
    force_http = settings.FORCE_HTTP_WHEN_SSL_DISABLED
    
    if ssl_exempt:
        print(f"  - Rutas exentas de SSL: {', '.join(ssl_exempt)}")
    else:
        print("  - Rutas exentas de SSL: Ninguna")
    
    print(f"  - Forzar HTTP cuando SSL deshabilitado: {force_http}")
    
    print()
    print("🌍 Middleware:")
    middlewares = settings.MIDDLEWARE
    ssl_middleware = 'orchestrator.middleware.ConditionalSSLRedirectMiddleware'
    
    if ssl_middleware in middlewares:
        index = middlewares.index(ssl_middleware) + 1
        print(f"  ✓ ConditionalSSLRedirectMiddleware encontrado (posición {index})")
    else:
        print("  ⚠️  ConditionalSSLRedirectMiddleware NO encontrado")
    
    print()
    print("=" * 70)
    print()
    
    # Recomendaciones
    print("💡 Recomendaciones:")
    
    if settings.DEBUG:
        print("  - Estás en modo desarrollo. Para probar SSL, configura:")
        print("    DEBUG=False")
        print("    ENABLE_SSL=True")
    elif not settings.ENABLE_SSL:
        print("  - SSL está deshabilitado.")
        print("  - Para habilitar HTTPS, configura: ENABLE_SSL=True")
    else:
        print("  ✓ Configuración SSL lista para producción")
        print("  - Asegúrate de tener un certificado SSL válido configurado")
        print("  - Verifica que ALLOWED_HOSTS incluye tu dominio")
    
    print()
    print("=" * 70)


if __name__ == "__main__":
    try:
        check_ssl_configuration()
    except Exception as e:
        print(f"❌ Error al verificar configuración: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
