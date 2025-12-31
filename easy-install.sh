#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}==================================================${NC}"
echo -e "${BLUE}       Community SH - Auto Installer              ${NC}"
echo -e "${BLUE}==================================================${NC}"

# 1. Update System
echo -e "\n${GREEN}[1/5] Updating system packages...${NC}"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq ca-certificates curl gnupg git nano

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo -e "\n${GREEN}[2/5] Installing Docker...${NC}"
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    echo \
      "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    sudo systemctl start docker
    sudo systemctl enable docker
else
    echo -e "\n${GREEN}[2/5] Docker already installed, skipping...${NC}"
fi

# 3. Clone Repository
echo -e "\n${GREEN}[3/5] Setting up Community SH...${NC}"
INSTALL_DIR="/opt/community-sh"

if [ -d "$INSTALL_DIR" ]; then
    echo "Directory $INSTALL_DIR already exists. Updating..."
    cd $INSTALL_DIR
    git pull
else
    git clone https://github.com/falconsoft3d/community-sh.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 4. Auto-configure environment
echo -e "\n${GREEN}[4/5] Configuring environment...${NC}"
PUBLIC_IP=$(curl -4 -s ifconfig.me 2>/dev/null || curl -4 -s icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')

# Generate secrets
SECRET_KEY=$(openssl rand -base64 50 | tr -d '\n/')
DB_PASSWORD="postgres"  # Default password for simplicity

# Create .env file with default configuration
cat > .env <<EOL
# Django Configuration
DJANGO_SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=*

# Host path for Docker mounts
HOST_WORKDIR=$(pwd)

# Database Configuration
DB_PASSWORD=${DB_PASSWORD}
DATABASE_URL=postgres://postgres:${DB_PASSWORD}@db:5432/community_sh

# Network Configuration
SERVER_IP=${PUBLIC_IP}
# Server IP: ${PUBLIC_IP}
# To restrict access, edit ALLOWED_HOSTS above
# Example: ALLOWED_HOSTS=your-domain.com,www.your-domain.com,${PUBLIC_IP}
EOL

echo -e "${GREEN}✓ Configuration file created${NC}"

# 5. Start Services
echo -e "\n${GREEN}[5/5] Starting services...${NC}"

# Ensure instances directory exists and has correct permissions for Docker containers
mkdir -p instances
sudo chmod -R 777 instances

sudo docker compose down --remove-orphans 2>/dev/null || true
sudo docker compose up -d --build

# Wait for services
echo -e "${YELLOW}Waiting for services to start...${NC}"
sleep 10

echo -e "\n${BLUE}==================================================${NC}"
echo -e "${GREEN}   ✨ Installation Complete! ✨   ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo -e "\n${GREEN}Access your application:${NC}"
echo -e "  → http://${PUBLIC_IP}:8000"
echo -e "\n${YELLOW}Configuration:${NC}"
echo -e "  → ALLOWED_HOSTS: * (all IPs allowed)"
echo -e "  → DEBUG: False"
echo -e "  → Database: PostgreSQL"
echo -e "  → DB Password: postgres (default)"
echo -e "\n${YELLOW}Configuration file:${NC}"
echo -e "  ${INSTALL_DIR}/.env"
echo -e "  Edit with: ${GREEN}nano ${INSTALL_DIR}/.env${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo -e "  1. Create admin user:"
echo -e "     ${GREEN}cd ${INSTALL_DIR} && sudo docker compose exec app python manage.py createsuperuser${NC}"
echo -e "\n  2. View logs:"
echo -e "     ${GREEN}cd ${INSTALL_DIR} && sudo docker compose logs -f app${NC}"
echo -e "\n  3. Customize settings (optional):"
echo -e "     ${GREEN}nano ${INSTALL_DIR}/.env${NC}"
echo -e "     ${GREEN}cd ${INSTALL_DIR} && sudo docker compose restart${NC}"
echo -e "\n${RED}Security:${NC}"
echo -e "  ⚠  Default DB password is 'postgres' - change it in .env for production"
echo -e "  ⚠  Consider setting specific ALLOWED_HOSTS in .env"
echo -e "  ⚠  Configure SSL in admin panel for HTTPS"
echo -e "${BLUE}==================================================${NC}"
