# Community SH - Odoo Hosting Orchestrator

🐳 Django-based orchestration platform for deploying and managing Odoo instances using Docker.

## ✨ Features
- 🚀 Deploy Odoo instances (v14-v17) using Docker
- 🌐 Automatic subdomain assignment with Traefik
- 🔗 GitHub integration for custom addons
- 🎛️ Start/Stop/Restart instance controls
- 💾 Automated backups and restore
- 🔐 SSL/HTTPS with Let's Encrypt auto-generation
- 📊 Metrics and monitoring dashboard
- 💻 Interactive container console
- 👥 User management system
- 📦 Requirements.txt installer
- 🔄 Instance duplication

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Docker Desktop (or Docker Engine) running
- Git

### 1. Installation

**Option 1: Quick Install (Recommended)**
Run this command on your fresh server:
```bash
curl -sL https://raw.githubusercontent.com/falconsoft3d/community-sh/main/easy-install.sh | sudo bash
```

**Option 2: Review and Run**
If you prefer to inspect the script first:
```bash
wget https://raw.githubusercontent.com/falconsoft3d/community-sh/main/easy-install.sh
chmod +x easy-install.sh
sudo ./easy-install.sh
```

**Option 3: Update**
```bash
git pull
docker-compose up -d --build
docker-compose exec app python manage.py migrate
```

**Docker Compose Commands Local**
```bash
docker-compose up -d --build app
docker-compose up -d --build
docker-compose logs -f cron
docker-compose restart app
docker-compose down
docker-compose logs --tail=100 app
```

```bash
sudo docker compose restart app
```

**Eliminar Dockers**
```bash
cd /opt/community-sh
sudo docker compose down
sudo docker compose down -v
sudo docker compose down -v --rmi all


sudo docker compose down
sudo docker stop $(sudo docker ps -aq) 2>/dev/null || true
sudo docker volume prune -f
sudo docker compose up -d
sleep 15
```

# 1. Limpieza (si no la has hecho ya)
```bash
sudo docker stop $(sudo docker ps -aq) 2>/dev/null
sudo docker rm $(sudo docker ps -aq) 2>/dev/null
sudo docker volume rm $(sudo docker volume ls -q) 2>/dev/null
sudo rm -rf /opt/community-sh
```

## 🔒 SSL/HTTPS Configuration

The platform supports conditional SSL/HTTPS configuration:

- **Enable SSL**: Set `ENABLE_SSL=True` to force all traffic to HTTPS
- **Disable SSL**: Set `ENABLE_SSL=False` to allow HTTP traffic

For detailed configuration instructions, see [SSL/HTTPS Documentation](docs/SSL_HTTPS_CONFIG.md).

To verify your SSL configuration, run:
```bash
python scripts/check_ssl_config.py
```

## 🛠️ Troubleshooting

### Check SSL Configuration
```bash
python scripts/check_ssl_config.py
```

### View Logs
```bash
docker-compose logs -f app
```

**Made with ❤️ for the Marlon Falcón Hernández**

