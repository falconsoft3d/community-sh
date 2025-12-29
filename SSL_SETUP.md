# Configuración de SSL/HTTPS con Let's Encrypt

## 🔐 Funcionalidad de Autogeneración de Certificados SSL

Esta aplicación ahora incluye la capacidad de generar automáticamente certificados SSL gratuitos usando Let's Encrypt (Certbot).

## 📋 Requisitos Previos

1. **Dominio configurado**: Tu dominio debe apuntar a la IP de este servidor
2. **Puerto 80 disponible**: Certbot necesita el puerto 80 para la verificación
3. **Permisos sudo**: Se requieren permisos de administrador para instalar certificados
4. **Email válido**: Para notificaciones de renovación de Let's Encrypt

## 🚀 Cómo Usar

### Desde la Interfaz Web

1. Navega a **Configuración** (`/settings/`)
2. En la sección "Configuración de Dominio y SSL"
3. Haz clic en **"Generar Certificado SSL"**
4. Completa el formulario:
   - **Dominio**: Tu dominio (ej: `ejemplo.com` o `www.ejemplo.com`)
   - **Email**: Tu email para notificaciones de Let's Encrypt
5. Haz clic en **"Generar Certificado Ahora"**

### El proceso automáticamente:

✅ Verifica si Certbot está instalado (lo instala si es necesario)
✅ Genera el certificado SSL usando Let's Encrypt
✅ Guarda las rutas de los certificados en la configuración
✅ Activa SSL/HTTPS automáticamente

## 📂 Ubicación de los Certificados

Los certificados generados se almacenan en:

- **Certificado**: `/etc/letsencrypt/live/TU_DOMINIO/fullchain.pem`
- **Clave privada**: `/etc/letsencrypt/live/TU_DOMINIO/privkey.pem`

## 🔄 Renovación de Certificados

Los certificados de Let's Encrypt son válidos por 90 días. Para renovarlos:

```bash
sudo certbot renew
```

O puedes configurar un cron job para renovación automática:

```bash
# Agregar al crontab (crontab -e)
0 0 * * 0 /usr/bin/certbot renew --quiet
```

## ⚠️ Troubleshooting

### Error: Puerto 80 no disponible
- Asegúrate de que ningún servicio esté usando el puerto 80
- Detén temporalmente servicios como Apache o Nginx

### Error: Dominio no apunta al servidor
- Verifica la configuración DNS de tu dominio
- Espera a que los cambios DNS se propaguen (puede tomar hasta 48 horas)

### Error: Permisos insuficientes
- Asegúrate de tener permisos sudo
- Ejecuta: `sudo visudo` para verificar permisos

## 🛠️ Instalación Manual de Certbot

Si la instalación automática falla, instala Certbot manualmente:

### macOS (usando Homebrew)
```bash
brew install certbot
```

### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install certbot
```

### CentOS/RHEL
```bash
sudo yum install certbot
```

## 🔧 Configuración Avanzada

### Certificados Wildcard
Para subdominios wildcard (`*.ejemplo.com`):

```bash
sudo certbot certonly \
  --manual \
  --preferred-challenges dns \
  --email tu@email.com \
  -d "*.ejemplo.com" \
  -d "ejemplo.com"
```

### Usar DNS Challenge
Si el puerto 80 no está disponible, usa DNS challenge:

```bash
sudo certbot certonly \
  --manual \
  --preferred-challenges dns \
  --email tu@email.com \
  -d ejemplo.com
```

## 📚 Recursos Adicionales

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Certbot Documentation](https://certbot.eff.org/docs/)
- [SSL Labs Test](https://www.ssllabs.com/ssltest/) - Prueba tu configuración SSL

## 🤝 Soporte

Si encuentras problemas, revisa:
1. Los logs de Django en la terminal
2. Los logs de Certbot: `/var/log/letsencrypt/`
3. La configuración de tu dominio DNS
