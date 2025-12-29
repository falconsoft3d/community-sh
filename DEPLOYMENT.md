# 🚀 Guía de Despliegue en Producción - Community SH

## ✅ Checklist Pre-Despliegue

### 1. Requisitos del Servidor
- [ ] Ubuntu/Debian 20.04+ o CentOS/RHEL 8+
- [ ] Python 3.8+
- [ ] Docker y Docker Compose instalados
- [ ] Nginx (opcional, como proxy reverso)
- [ ] Dominio configurado apuntando al servidor
- [ ] Puertos 80 y 443 abiertos

### 2. Variables de Entorno
Crea un archivo `.env` en el directorio raíz:

```bash
# Django Settings
DJANGO_SECRET_KEY=tu_clave_secreta_super_larga_y_aleatoria_aqui
DEBUG=False
ALLOWED_HOSTS=tudominio.com,www.tudominio.com

# Database (opcional, para producción se recomienda PostgreSQL)
# DATABASE_URL=postgresql://user:password@localhost:5432/communitysh

# Email (opcional, para notificaciones)
# EMAIL_HOST=smtp.gmail.com
# EMAIL_PORT=587
# EMAIL_USE_TLS=True
# EMAIL_HOST_USER=tu@email.com
# EMAIL_HOST_PASSWORD=tu_password
```

### 3. Configuración de Seguridad
- [ ] Cambiar `SECRET_KEY` por una clave aleatoria única
- [ ] Establecer `DEBUG=False`
- [ ] Configurar `ALLOWED_HOSTS` con tu dominio
- [ ] Configurar firewall (UFW/firewalld)
- [ ] Instalar y configurar fail2ban

### 4. Base de Datos
```bash
# Para desarrollo (SQLite - ya incluido)
python manage.py migrate

# Para producción (PostgreSQL recomendado)
# 1. Instalar PostgreSQL
# 2. Crear base de datos
# 3. Actualizar settings.py o DATABASE_URL
# 4. python manage.py migrate
```

### 5. Archivos Estáticos
```bash
# Recolectar archivos estáticos
python manage.py collectstatic --noinput

# Los archivos se copiarán a ./staticfiles/
```

---

## 🔧 Instalación con install.sh

El script `install.sh` automatiza la instalación:

```bash
# Descargar el proyecto
git clone <tu-repo>
cd community-sh

# Hacer el script ejecutable
chmod +x install.sh

# Ejecutar instalación
./install.sh
```

**El script hace:**
1. ✅ Verifica prerequisitos (Docker, Git, Python)
2. ✅ Crea entorno virtual Python
3. ✅ Instala dependencias
4. ✅ Crea red Docker 'web'
5. ✅ Inicia Traefik (proxy reverso)
6. ✅ Ejecuta migraciones de base de datos
7. ✅ Crea usuario administrador
8. ✅ Crea directorios necesarios (instances, backups, media)

---

## 🌐 Opción 1: Despliegue con Gunicorn + Nginx

### Paso 1: Instalar Gunicorn
```bash
source venv/bin/activate
pip install gunicorn
```

### Paso 2: Crear servicio systemd
```bash
sudo nano /etc/systemd/system/communitysh.service
```

```ini
[Unit]
Description=Community SH Gunicorn daemon
After=network.target

[Service]
User=tu_usuario
Group=www-data
WorkingDirectory=/ruta/completa/a/community-sh
Environment="PATH=/ruta/completa/a/community-sh/venv/bin"
ExecStart=/ruta/completa/a/community-sh/venv/bin/gunicorn \
          --workers 3 \
          --bind unix:/ruta/completa/a/community-sh/communitysh.sock \
          config.wsgi:application

[Install]
WantedBy=multi-user.target
```

### Paso 3: Configurar Nginx
```bash
sudo nano /etc/nginx/sites-available/communitysh
```

```nginx
server {
    listen 80;
    server_name tudominio.com www.tudominio.com;

    client_max_body_size 100M;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        alias /ruta/completa/a/community-sh/staticfiles/;
    }

    location /media/ {
        alias /ruta/completa/a/community-sh/media/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/ruta/completa/a/community-sh/communitysh.sock;
    }
}
```

### Paso 4: Activar y iniciar servicios
```bash
# Activar sitio Nginx
sudo ln -s /etc/nginx/sites-available/communitysh /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Iniciar servicio
sudo systemctl start communitysh
sudo systemctl enable communitysh
sudo systemctl status communitysh
```

---

## 🔐 Paso 5: Configurar SSL/HTTPS

### Opción A: Usar la interfaz web (Recomendado)
1. Accede a `http://tudominio.com/settings/`
2. En "Configuración de Dominio y SSL"
3. Click en "Generar Certificado SSL"
4. Ingresa tu dominio y email
5. Click "Generar Certificado Ahora"

### Opción B: Manual con Certbot
```bash
# Instalar Certbot
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx

# Generar certificado
sudo certbot --nginx -d tudominio.com -d www.tudominio.com

# Renovación automática (ya está configurado por Certbot)
sudo certbot renew --dry-run
```

---

## 📦 Opción 2: Despliegue con Docker (TODO)

```bash
# Construir imagen
docker build -t communitysh:latest .

# Ejecutar contenedor
docker run -d \
  --name communitysh \
  -p 8000:8000 \
  -v $(pwd)/db.sqlite3:/app/db.sqlite3 \
  -v $(pwd)/media:/app/media \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env-file .env \
  communitysh:latest
```

---

## 🔄 Actualización del Sistema

```bash
# Detener servicio
sudo systemctl stop communitysh

# Actualizar código
cd /ruta/a/community-sh
git pull origin main

# Activar entorno virtual
source venv/bin/activate

# Actualizar dependencias
pip install -r requirements.txt

# Ejecutar migraciones
python manage.py migrate

# Recolectar estáticos
python manage.py collectstatic --noinput

# Reiniciar servicio
sudo systemctl start communitysh
```

---

## 📊 Monitoreo y Logs

```bash
# Ver logs del servicio
sudo journalctl -u communitysh -f

# Ver logs de Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Ver logs de Docker
docker-compose logs -f traefik
```

---

## 🛡️ Seguridad Post-Instalación

### 1. Configurar Firewall (UFW)
```bash
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS
sudo ufw enable
sudo ufw status
```

### 2. Configurar fail2ban
```bash
sudo apt-get install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 3. Backups Automáticos
Configura backups regulares de:
- Base de datos: `db.sqlite3`
- Archivos media: `media/`
- Backups de instancias: `backups/`

```bash
# Ejemplo de script de backup
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf backup_$DATE.tar.gz db.sqlite3 media/ backups/
# Subir a S3, Dropbox, etc.
```

---

## 🚨 Solución de Problemas

### Error: "Bad Gateway 502"
- Verificar que Gunicorn está corriendo: `sudo systemctl status communitysh`
- Verificar socket: `ls -la communitysh.sock`
- Revisar logs: `sudo journalctl -u communitysh -n 50`

### Error: Static files no se cargan
```bash
python manage.py collectstatic --clear --noinput
sudo systemctl restart communitysh
```

### Error: Permission denied en Docker
```bash
sudo usermod -aG docker $USER
# Cerrar sesión y volver a iniciar
```

---

## 📞 Soporte

Si encuentras problemas durante el despliegue:
1. Revisa los logs del sistema
2. Verifica las variables de entorno
3. Consulta la documentación oficial de Django
4. Abre un issue en el repositorio

---

## 🎯 Comandos Rápidos de Referencia

```bash
# Activar entorno
source venv/bin/activate

# Ejecutar migraciones
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser

# Recolectar estáticos
python manage.py collectstatic

# Iniciar desarrollo
python manage.py runserver

# Iniciar producción (Gunicorn)
sudo systemctl start communitysh

# Reiniciar servicios
sudo systemctl restart communitysh
sudo systemctl restart nginx

# Ver logs
sudo journalctl -u communitysh -f
```

---

**¡Listo! Tu Community SH está en producción 🚀**
