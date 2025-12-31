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
echo -e "\n${GREEN}[1/6] Updating system packages...${NC}"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq ca-certificates curl gnupg git nano

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo -e "\n${GREEN}[2/6] Installing Docker...${NC}"
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
    echo -e "\n${GREEN}[2/6] Docker already installed, skipping...${NC}"
fi

# 3. Clone Repository
echo -e "\n${GREEN}[3/6] Setting up Community SH...${NC}"
INSTALL_DIR="/opt/community-sh"

if [ -d "$INSTALL_DIR" ]; then
    echo "Directory $INSTALL_DIR already exists. Updating..."
    cd $INSTALL_DIR
    git pull
else
    # Replace this with your actual public repository URL
    git clone https://github.com/falconsoft3d/community-sh.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 4. Detect and Configure Network Settings
echo -e "\n${GREEN}[4/6] Configuring network settings...${NC}"

# Try to detect public IP
echo -e "${YELLOW}Detecting server IP address...${NC}"
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s icanhazip.com 2>/dev/null || echo "")

if [ -z "$PUBLIC_IP" ]; then
    # Fallback to local IP
    PUBLIC_IP=$(hostname -I | awk '{print $1}')
fi

echo -e "${GREEN}Detected IP: ${PUBLIC_IP}${NC}"
read -p "Is this correct? (Y/n): " IP_CONFIRM
if [[ $IP_CONFIRM =~ ^[Nn]$ ]]; then
    read -p "Enter your server IP address: " PUBLIC_IP
fi

# Ask for domain (optional)
echo -e "\n${YELLOW}Domain Configuration (Optional)${NC}"
read -p "Do you have a domain name? (y/N): " HAS_DOMAIN

ALLOWED_HOSTS="${PUBLIC_IP}"

if [[ $HAS_DOMAIN =~ ^[Yy]$ ]]; then
    read -p "Enter your domain (e.g., example.com): " DOMAIN
    if [ ! -z "$DOMAIN" ]; then
        ALLOWED_HOSTS="${PUBLIC_IP},${DOMAIN},www.${DOMAIN}"
        echo -e "${GREEN}✓ Domain configured: ${DOMAIN}${NC}"
    fi
fi

echo -e "${GREEN}ALLOWED_HOSTS will be set to: ${ALLOWED_HOSTS}${NC}"

# 5. Configure Environment
echo -e "\n${GREEN}[5/6] Configuring environment...${NC}"

# Generate a random secret key
SECRET_KEY=$(openssl rand -base64 50 | tr -d '\n/')

# Ask for database password
read -p "Enter PostgreSQL password (default: postgres): " DB_PASSWORD
DB_PASSWORD=${DB_PASSWORD:-postgres}

# Create or update .env file
cat > .env <<EOL
# Django Configuration
DJANGO_SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${ALLOWED_HOSTS}

# Database Configuration
DATABASE_URL=postgres://postgres:${DB_PASSWORD}@db:5432/community_sh

# Network Configuration
SERVER_IP=${PUBLIC_IP}
$([ ! -z "$DOMAIN" ] && echo "DOMAIN=${DOMAIN}")
EOL

echo -e "${GREEN}✓ Environment configured successfully${NC}"

# Update docker-compose.yml with correct settings
echo -e "${YELLOW}Updating docker-compose configuration...${NC}"
sed -i "s/POSTGRES_PASSWORD=postgres/POSTGRES_PASSWORD=${DB_PASSWORD}/g" docker-compose.yml 2>/dev/null || true

# 6. Start Services
echo -e "\n${GREEN}[6/6] Starting services...${NC}"
sudo docker compose down --remove-orphans 2>/dev/null || true
sudo docker compose up -d --build

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to start...${NC}"
sleep 10

echo -e "\n${BLUE}==================================================${NC}"
echo -e "${GREEN}   ✨ Installation Complete! ✨   ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo -e "\n${GREEN}Access URLs:${NC}"
echo -e "  → By IP:     http://${PUBLIC_IP}:8000"
[ ! -z "$DOMAIN" ] && echo -e "  → By Domain: http://${DOMAIN}:8000"
echo -e "\n${YELLOW}Important Configuration:${NC}"
echo -e "  → ALLOWED_HOSTS: ${ALLOWED_HOSTS}"
echo -e "  → DEBUG: False (Production Mode)"
echo -e "  → Database: PostgreSQL"
echo -e "\n${YELLOW}Next steps:${NC}"
echo -e "  1. Create admin user:"
echo -e "     ${GREEN}cd $INSTALL_DIR && sudo docker compose exec app python manage.py createsuperuser${NC}"
echo -e "\n  2. View logs:"
echo -e "     ${GREEN}cd $INSTALL_DIR && sudo docker compose logs -f${NC}"
echo -e "\n  3. Configure SSL (recommended for production):"
echo -e "     ${GREEN}Go to Settings → Domain & SSL in the admin panel${NC}"
echo -e "\n  4. Update settings:"
echo -e "     ${GREEN}nano $INSTALL_DIR/.env${NC}"
echo -e "${BLUE}==================================================${NC}"
