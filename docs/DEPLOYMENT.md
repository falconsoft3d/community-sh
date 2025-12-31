# 🚀 Docker Deployment Guide - Community SH

This guide describes how to deploy Community SH using Docker and Docker Compose. This is the **recommended** method for both development and production.

## 📋 Prerequisites

- **Server**: Ubuntu 20.04+, Debian 11+, or CentOS 8+
- **Resources**: Minimum 2 GB RAM (4 GB recommended for Odoo instances), 2 CPU cores
- **Software**: 
  - [Docker Engine](https://docs.docker.com/engine/install/)
  - [Docker Compose](https://docs.docker.com/compose/install/) (or `docker compose` plugin)

## 🛠️ Step-by-Step Installation

### 1. Install Docker
If you haven't installed Docker yet, execute the following commands (for Ubuntu/Debian):

```bash
# Update repositories
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow running docker without sudo (optional but recommended)
sudo usermod -aG docker $USER
# NOTE: Log out and log back in for this to take effect!
```

### 2. Clone the Repository
Clone the project code to your server location (e.g., `/opt/community-sh` or your home directory).

```bash
git clone https://github.com/your-repo/community-sh.git
cd community-sh
```

### 3. Configuration
The default `docker-compose.yml` is set up to work out-of-the-box, but for production, you **MUST** secure it.

Edit `docker-compose.yml` or create a `.env` file to set secure values:

```bash
nano docker-compose.yml
```

**Critical changes for Production:**
- Change `DJANGO_SECRET_KEY` to a random long string.
- Change `POSTGRES_PASSWORD` in both `db` service and `DATABASE_URL`.
- Set `DEBUG=False` in `app` and `cron` services.
- Update `ALLOWED_HOSTS` to your real domain (e.g. `community.yourdomain.com`).
- Update Traefik labels if you are using a real domain instead of `localhost`.

### 4. Start the Application
Run the following command to build and start all containers in detached mode:

```bash
docker-compose up -d --build
```

This will start:
- **db**: PostgreSQL database
- **app**: Main Django application (port 8000 internally, exposed via Traefik)
- **cron**: Background task scheduler for backups
- **traefik**: Reverse proxy (ports 80 and 8080)

### 5. Create Admin User
Once the containers are running, create your superuser:

```bash
docker-compose exec app python manage.py createsuperuser
```

Follow the prompts to set username (e.g., `admin`), email, and password.

---

## 🚦 Management Commands

### Check Status
See running containers:
```bash
docker-compose ps
```

### View Logs
To see logs for all services (follow mode):
```bash
docker-compose logs -f
```
To see specific logs (e.g., for the cron job):
```bash
docker-compose logs -f cron
```

### Update Application
When you have new code changes:
```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild and restart containers
docker-compose up -d --build
```

### Restart a Specific Service
If you made changes to python code and need to restart the app:
```bash
docker-compose restart app
```

### Stop Everything
```bash
docker-compose down
```

### Database Backups
The `cron` container handles automated backups. To run a backup manually:
```bash
docker-compose exec app python manage.py run_auto_backups
```

---

## 🛡️ SSL Configuration (Production)
For production with a real domain, Traefik handles SSL automatically with Let's Encrypt. You need to update `docker-compose.yml` to enable the ACME (Let's Encrypt) resolver.

See the [Traefik Documentation](https://doc.traefik.io/traefik/https/acme/) for adding the certificate resolver to the `traefik` service command arguments.
