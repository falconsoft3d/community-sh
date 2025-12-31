#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
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
    # Replace this with your actual public repository URL
    git clone https://github.com/falconsoft3d/community-sh.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 4. Configure Environment
echo -e "\n${GREEN}[4/5] Configuring environment...${NC}"
if [ ! -f .env ]; then
    # Generate a random secret key
    SECRET_KEY=$(openssl rand -base64 50 | tr -d '\n/')
    
    # Create simple .env for production
    cat > .env <<EOL
DJANGO_SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=*
DATABASE_URL=postgres://postgres:postgres@db:5432/community_sh
EOL
    echo "Created .env file with generated secrets."
fi

# 5. Start Services
echo -e "\n${GREEN}[5/5] Starting services...${NC}"
sudo docker compose down --remove-orphans
sudo docker compose up -d --build

echo -e "\n${BLUE}==================================================${NC}"
echo -e "${GREEN}   ✨ Installation Complete! ✨   ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo -e "Access your application at: http://$(curl -s ifconfig.me)"
echo -e "\nNext steps:"
echo -e "1. Create admin user:  cd $INSTALL_DIR && sudo docker compose exec app python manage.py createsuperuser"
echo -e "2. View logs:          cd $INSTALL_DIR && sudo docker compose logs -f"
echo -e "${BLUE}==================================================${NC}"
