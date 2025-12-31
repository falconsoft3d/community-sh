# Configuración SSL/HTTPS

Esta guía explica cómo habilitar y configurar SSL/HTTPS en la aplicación Community-SH.

## Descripción General

La aplicación cuenta con un sistema de SSL/HTTPS condicional que permite:
- **Forzar HTTPS**: Cuando SSL está habilitado, todas las peticiones HTTP se redirigen automáticamente a HTTPS
- **Permitir HTTP**: Cuando SSL está deshabilitado, se permite el tráfico HTTP normal

## Configuración Básica

### 1. Habilitar SSL/HTTPS

Para habilitar SSL/HTTPS, configura la variable de entorno `ENABLE_SSL` en tu archivo `.env`:

```bash
ENABLE_SSL=True
```

### 2. Deshabilitar SSL/HTTPS (permitir HTTP)

Para deshabilitar SSL y permitir HTTP, configura:

```bash
ENABLE_SSL=False
```

## Comportamiento

### Con ENABLE_SSL=True (Producción con HTTPS)

Cuando `ENABLE_SSL=True` y `DEBUG=False`, la aplicación:
- ✅ Redirige automáticamente todas las peticiones HTTP a HTTPS
- ✅ Activa `SECURE_SSL_REDIRECT=True`
- ✅ Activa `SESSION_COOKIE_SECURE=True` (cookies solo por HTTPS)
- ✅ Activa `CSRF_COOKIE_SECURE=True` (tokens CSRF solo por HTTPS)
- ✅ Activa HSTS (HTTP Strict Transport Security) por 1 año
- ✅ Incluye subdominios en HSTS
- ✅ Habilita HSTS preload

### Con ENABLE_SSL=False (Producción sin HTTPS)

Cuando `ENABLE_SSL=False` y `DEBUG=False`, la aplicación:
- ✅ Permite tráfico HTTP normal
- ✅ Desactiva `SECURE_SSL_REDIRECT=False`
- ✅ Desactiva `SESSION_COOKIE_SECURE=False`
- ✅ Desactiva `CSRF_COOKIE_SECURE=False`
- ✅ Mantiene otras configuraciones de seguridad (XSS, Content-Type, etc.)

### En Desarrollo (DEBUG=True)

Cuando `DEBUG=True`, todas las configuraciones SSL se ignoran:
- ✅ Permite tanto HTTP como HTTPS
- ✅ No fuerza redirecciones
- ✅ Facilita el desarrollo local

## Configuraciones Avanzadas

### Excluir Rutas de Redirección HTTPS

Si necesitas que ciertas rutas NO sean redirigidas a HTTPS (por ejemplo, health checks o webhooks externos), configura:

```bash
SSL_REDIRECT_EXEMPT=/health,/status,/webhook
```

### Forzar HTTP cuando SSL está Deshabilitado

⚠️ **ADVERTENCIA**: Solo para desarrollo/testing

Si necesitas que la aplicación fuerce HTTP cuando SSL está deshabilitado:

```bash
FORCE_HTTP_WHEN_SSL_DISABLED=True
```

Esto redirigirá peticiones HTTPS a HTTP automáticamente cuando `ENABLE_SSL=False`.

## Ejemplos de Configuración

### Ejemplo 1: Producción con HTTPS (Recomendado)

```bash
# .env
DEBUG=False
ENABLE_SSL=True
ALLOWED_HOSTS=midominio.com,www.midominio.com
```

**Resultado**: Todas las peticiones HTTP serán redirigidas a HTTPS automáticamente.

### Ejemplo 2: Producción sin HTTPS (Detrás de un Proxy/Load Balancer)

```bash
# .env
DEBUG=False
ENABLE_SSL=False
ALLOWED_HOSTS=miserver.local
```

**Resultado**: Permite tanto HTTP como HTTPS sin redirecciones.

### Ejemplo 3: Desarrollo Local

```bash
# .env
DEBUG=True
ENABLE_SSL=False
ALLOWED_HOSTS=localhost,127.0.0.1
```

**Resultado**: Permite desarrollo sin restricciones SSL.

## Casos de Uso

### 1. Servidor con Certificado SSL/TLS Propio

```bash
ENABLE_SSL=True
```

La aplicación manejará las redirecciones HTTPS automáticamente.

### 2. Detrás de un Reverse Proxy (Nginx, Traefik, etc.)

```bash
ENABLE_SSL=False
```

El proxy maneja SSL/TLS, la aplicación recibe tráfico HTTP interno.

### 3. Desarrollo Local

```bash
DEBUG=True
ENABLE_SSL=False
```

Sin restricciones para desarrollo.

## Verificación

Para verificar que SSL está funcionando correctamente:

1. **Con SSL habilitado**: Intenta acceder a `http://tudominio.com` y verifica que redirige a `https://tudominio.com`

2. **Sin SSL**: Verifica que `http://tudominio.com` funciona sin redirección

3. **Revisa los logs de Django** para ver las configuraciones aplicadas:

```bash
docker-compose logs web | grep -i ssl
```

## Troubleshooting

### Problema: "DisallowedHost" después de habilitar SSL

**Solución**: Asegúrate de que `ALLOWED_HOSTS` incluye tu dominio:

```bash
ALLOWED_HOSTS=tudominio.com,www.tudominio.com
```

### Problema: Redirección infinita

**Solución**: Si estás detrás de un proxy, configura:

```bash
ENABLE_SSL=False
```

Y deja que el proxy maneje SSL.

### Problema: Las cookies no funcionan

**Solución**: Verifica que tu configuración SSL coincide con el protocolo real:
- Si usas HTTPS, `ENABLE_SSL=True`
- Si usas HTTP, `ENABLE_SSL=False`

## Seguridad

⚠️ **Importante para Producción**:

1. **Siempre usa HTTPS en producción** cuando sea posible
2. Configura `ENABLE_SSL=True` si tu servidor tiene certificado SSL
3. Nunca uses `FORCE_HTTP_WHEN_SSL_DISABLED=True` en producción
4. Mantén `DEBUG=False` en producción
5. Usa certificados válidos (Let's Encrypt es gratuito)

## Referencias

- [Django Security Settings](https://docs.djangoproject.com/en/stable/topics/security/)
- [HTTPS Best Practices](https://developer.mozilla.org/en-US/docs/Web/Security/Transport_Layer_Security)
- [HSTS Preload](https://hstspreload.org/)
