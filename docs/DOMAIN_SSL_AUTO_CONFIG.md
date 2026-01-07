# Configuración Automática de Dominio y SSL/HTTPS

## 🎯 Descripción General

El sistema ahora soporta configuración automática de dominios personalizados y certificados SSL/HTTPS con Let's Encrypt, integrándose completamente con Traefik.

## 📋 Funcionalidades Implementadas

### 1. Configuración Automática de Dominio Principal

Cuando configuras un dominio principal en **Settings → Domain & SSL**:

- ✅ El sistema actualiza automáticamente la configuración de Traefik
- ✅ El dominio se agrega dinámicamente a ALLOWED_HOSTS
- ✅ Se crea una ruta HTTP para tu dominio personalizado
- ✅ Se acepta tanto el dominio principal como la variante con `www.`

**Ejemplo**: Si configuras `ejemplo.com`, el sistema aceptará peticiones a:
- `ejemplo.com`
- `www.ejemplo.com`

### 2. Generación Automática de Certificados SSL con HTTPS

Cuando generas un certificado SSL usando Let's Encrypt:

- ✅ El sistema genera el certificado automáticamente
- ✅ Actualiza la configuración de Traefik para usar HTTPS
- ✅ Configura redirección automática de HTTP a HTTPS
- ✅ Guarda las rutas de certificados en la configuración

## 🚀 Cómo Usar

### Paso 1: Configurar el Dominio Principal

1. Ve a **Configuración** (`/settings/`)
2. Haz clic en la pestaña **"Domain & SSL"**
3. En el campo **"Dominio Principal"**, ingresa tu dominio (ejemplo: `midominio.com`)
4. Haz clic en **"Guardar Configuración"**
5. Verás un mensaje indicando que debes reiniciar los servicios

### Paso 2: Aplicar la Configuración de Traefik

Ejecuta el siguiente comando para aplicar los cambios:

```bash
docker-compose up -d --force-recreate app
```

Esto actualizará el contenedor de la aplicación con las nuevas etiquetas de Traefik.

### Paso 3: Generar Certificado SSL (Opcional pero Recomendado)

**Requisitos previos:**
- Tu dominio debe apuntar a la IP de este servidor
- El puerto 80 debe estar disponible y accesible desde internet
- El puerto 443 debe estar disponible y accesible desde internet

**Pasos:**

1. En la misma pestaña **"Domain & SSL"**
2. Haz clic en **"Generar Certificado SSL"**
3. Completa el formulario:
   - **Dominio**: Se autocompletará con tu dominio principal
   - **Email**: Tu email para notificaciones de Let's Encrypt
4. Haz clic en **"Generar Certificado Ahora"**

El sistema:
- Instalará Certbot si no está disponible
- Generará el certificado SSL
- Actualizará la configuración para usar HTTPS
- Configurará Traefik para usar el certificado

### Paso 4: Aplicar la Configuración HTTPS

Ejecuta el siguiente comando para aplicar HTTPS:

```bash
docker-compose up -d --force-recreate app traefik
```

Esto reiniciará ambos servicios con la nueva configuración de HTTPS.

## 🔧 Configuración de Traefik

El archivo `docker-compose.yml` ha sido actualizado con:

### Nuevas Configuraciones

```yaml
traefik:
  command:
    - "--entrypoints.websecure.address=:443"
    - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
    - "--certificatesresolvers.letsencrypt.acme.email=admin@example.com"
    - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
  ports:
    - "443:443"  # Puerto HTTPS
  volumes:
    - "./letsencrypt:/letsencrypt"  # Almacenamiento de certificados
```

### Etiquetas Dinámicas del Contenedor App

Cuando configuras un dominio CON SSL:
```yaml
labels:
  - "traefik.http.routers.app-secure.rule=Host(`tudominio.com`) || Host(`www.tudominio.com`)"
  - "traefik.http.routers.app-secure.entrypoints=websecure"
  - "traefik.http.routers.app-secure.tls=true"
  - "traefik.http.routers.app-secure.tls.certresolver=letsencrypt"
  - "traefik.http.routers.app-http.middlewares=https-redirect"
```

Cuando configuras un dominio SIN SSL:
```yaml
labels:
  - "traefik.http.routers.app.rule=Host(`tudominio.com`) || Host(`www.tudominio.com`)"
  - "traefik.http.routers.app.entrypoints=web"
```

## 📝 Middleware Dinámico

### DynamicAllowedHostsMiddleware

Este middleware valida automáticamente los hosts permitidos basándose en:

- El dominio principal configurado en GitHubConfig
- Hosts predeterminados: `localhost`, `127.0.0.1`, `community.local`
- Variantes con `www.` del dominio principal

**Comportamiento:**
- ✅ En desarrollo (DEBUG=True): Permite todos los hosts
- ✅ En producción (DEBUG=False): Valida contra la lista dinámica
- ⚠️ Si el host no está permitido, devuelve un error 403

## 🔒 Seguridad

### Certificados Let's Encrypt

- Los certificados se almacenan en `/letsencrypt/acme.json`
- Traefik maneja automáticamente la renovación
- Los certificados son válidos por 90 días y se renuevan automáticamente

### Redirección HTTPS

Cuando SSL está habilitado:
- Todas las peticiones HTTP se redirigen automáticamente a HTTPS
- Se aplican headers de seguridad (HSTS, etc.)
- Las cookies se marcan como seguras

## 🛠️ Troubleshooting

### El dominio no funciona después de configurarlo

1. Verifica que tu dominio apunte a la IP del servidor:
   ```bash
   nslookup tudominio.com
   ```

2. Reinicia los servicios:
   ```bash
   docker-compose restart app traefik
   ```

3. Verifica los logs de Traefik:
   ```bash
   docker-compose logs -f traefik
   ```

### El certificado SSL no se genera

1. Verifica que el puerto 80 esté disponible:
   ```bash
   sudo lsof -i :80
   ```

2. Verifica que tu dominio apunte al servidor:
   ```bash
   curl http://tudominio.com
   ```

3. Revisa los logs de Certbot:
   ```bash
   sudo certbot certificates
   ```

### Errores de ALLOWED_HOSTS

Si ves errores de `DisallowedHost`:

1. Verifica que el dominio esté configurado en Settings
2. Reinicia la aplicación:
   ```bash
   docker-compose restart app
   ```

3. Si persiste, agrega el dominio manualmente a `.env`:
   ```bash
   ALLOWED_HOSTS=tudominio.com,www.tudominio.com,localhost
   ```

## 📚 Referencias

- [Documentación de Traefik](https://doc.traefik.io/traefik/)
- [Let's Encrypt](https://letsencrypt.org/)
- [Django ALLOWED_HOSTS](https://docs.djangoproject.com/en/stable/ref/settings/#allowed-hosts)

## 🎉 Mejoras Implementadas

1. **Automatización Completa**: No necesitas editar manualmente docker-compose.yml
2. **Integración con Traefik**: Configuración automática de rutas y SSL
3. **ALLOWED_HOSTS Dinámico**: Se actualiza automáticamente con el dominio configurado
4. **Let's Encrypt**: Generación automática de certificados SSL gratuitos
5. **Seguridad**: Redirección automática HTTPS y headers de seguridad

---

**Notas Importantes:**

- Asegúrate de que tu dominio apunte a la IP del servidor antes de configurar SSL
- Los puertos 80 y 443 deben estar disponibles y accesibles desde internet
- En desarrollo local, puedes trabajar sin SSL usando `localhost` o `community.local`
- Para producción, siempre usa HTTPS para mayor seguridad
