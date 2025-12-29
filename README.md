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

### Installation

**Option 1: Automated Installation (Recommended)**
```bash
# Clone the repository
git clone <your-repo-url>
cd community-sh

# Run the installer
chmod +x install.sh
./install.sh
```

The installer will:
- ✅ Check prerequisites
- ✅ Create Python virtual environment
- ✅ Install dependencies
- ✅ Set up Docker network
- ✅ Start Traefik reverse proxy
- ✅ Run database migrations
- ✅ Create admin user
- ✅ Set up directories

**Option 2: Manual Installation**
```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create Docker network
docker network create web

# 4. Start Traefik
docker-compose up -d

# 5. Run migrations
python manage.py migrate

# 6. Create superuser
python manage.py createsuperuser

# 7. Start server
python manage.py runserver
```

### Access the Application
Open [http://localhost:8000](http://localhost:8000)

## 📚 Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete production deployment guide
- **[SSL_SETUP.md](SSL_SETUP.md)** - SSL/HTTPS configuration with Let's Encrypt

## 🎯 Usage

1. **Create Instance**: Click "New Instance" and configure your Odoo setup
2. **Deploy**: Click "Deploy" to start the container
3. **Access Odoo**: Once running, click "Open Odoo" → `http://<name>.localhost`
4. **Manage**: Use the dashboard to stop, restart, backup, or duplicate instances
5. **Console**: Execute commands inside containers via the interactive console
6. **Backups**: Create and restore backups from the instance detail page

## 🔧 Configuration

### Environment Variables (Production)
Create a `.env` file (see `.env.example`):
```bash
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

### SSL/HTTPS Setup
1. Navigate to **Settings** → **Domain & SSL Configuration**
2. Click **"Generate SSL Certificate"**
3. Enter your domain and email
4. Click **"Generate Certificate Now"**

The system will automatically:
- Install Certbot (if needed)
- Generate Let's Encrypt certificate
- Configure HTTPS

## 🛠️ Tech Stack

- **Backend**: Django 6.0, Django REST Framework
- **Database**: SQLite (dev) / PostgreSQL (production recommended)
- **Container**: Docker, Docker Compose
- **Proxy**: Traefik v2.9
- **Frontend**: Tailwind CSS, Alpine.js
- **Icons**: Lucide Icons

## 📦 Project Structure

```
community-sh/
├── config/              # Django project settings
├── orchestrator/        # Main application
│   ├── models.py       # Database models
│   ├── views.py        # Views and API endpoints
│   ├── services.py     # Docker and SSL services
│   ├── templates/      # HTML templates
│   └── migrations/     # Database migrations
├── instances/          # Odoo instances data
├── backups/            # Instance backups
├── media/              # User uploads (avatars, etc.)
├── install.sh          # Automated installer
├── docker-compose.yml  # Traefik configuration
└── requirements.txt    # Python dependencies
```

## 🚀 Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete production deployment instructions including:
- Gunicorn + Nginx setup
- SSL configuration
- Security hardening
- Systemd service configuration
- Monitoring and logs

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- Inspired by [Odoo.sh](https://www.odoo.sh)
- Built with Django, Docker, and Traefik

## 📧 Support

For issues and questions, please open an issue on GitHub.

---

**Made with ❤️ for the Odoo community**

