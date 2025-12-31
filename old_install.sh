#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════╗"
echo "║     Community SH Installer            ║"
echo "║     Odoo Instance Orchestrator        ║"
echo "╚═══════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo -e "${RED}Please do not run as root${NC}"
   exit 1
fi

# Function to check command existence
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command_exists docker; then
    echo -e "${RED}Docker is not installed. Please install Docker first.${NC}"
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
    echo -e "${RED}Docker Compose is not installed.${NC}"
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

if ! command_exists git; then
    echo -e "${RED}Git is not installed. Please install Git first.${NC}"
    exit 1
fi

if ! command_exists python3; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3.8+ first.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All prerequisites met${NC}"

# Get installation directory
INSTALL_DIR="${INSTALL_DIR:-$HOME/community-sh}"
echo ""
echo -e "${YELLOW}Installation directory: ${INSTALL_DIR}${NC}"

# Clone repository
echo ""
echo -e "${YELLOW}Cloning Community SH repository...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory already exists. Pulling latest changes...${NC}"
    cd "$INSTALL_DIR"
    git pull
else
    git clone https://github.com/falconsoft3d/community-sh.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo -e "${GREEN}✓ Repository cloned${NC}"

# Create virtual environment
echo ""
echo -e "${YELLOW}Creating Python virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo -e "${GREEN}✓ Virtual environment created${NC}"

# Install Python dependencies
echo ""
echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1

echo -e "${GREEN}✓ Dependencies installed${NC}"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo ""
    echo -e "${YELLOW}Creating environment configuration...${NC}"
    cat > .env << EOF
SECRET_KEY=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
EOF
    echo -e "${GREEN}✓ Environment configured${NC}"
fi

# Run Django migrations
echo ""
echo -e "${YELLOW}Running database migrations...${NC}"
python manage.py migrate > /dev/null 2>&1

echo -e "${GREEN}✓ Database migrated${NC}"

# Start Traefik
echo ""
echo -e "${YELLOW}Starting Traefik reverse proxy...${NC}"
docker-compose up -d > /dev/null 2>&1

echo -e "${GREEN}✓ Traefik started${NC}"

# Create superuser
echo ""
echo -e "${YELLOW}Creating admin user...${NC}"
echo ""
read -p "Admin username (default: admin): " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

read -p "Admin email: " ADMIN_EMAIL
while [ -z "$ADMIN_EMAIL" ]; do
    read -p "Admin email (required): " ADMIN_EMAIL
done

read -sp "Admin password: " ADMIN_PASS
echo ""
while [ -z "$ADMIN_PASS" ]; do
    read -sp "Admin password (required): " ADMIN_PASS
    echo ""
done

python manage.py shell << EOF > /dev/null 2>&1
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$ADMIN_USER').exists():
    User.objects.create_superuser('$ADMIN_USER', '$ADMIN_EMAIL', '$ADMIN_PASS')
EOF

echo -e "${GREEN}✓ Admin user created${NC}"

# Create directories
mkdir -p instances backups

# Installation complete
echo ""
echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════╗"
echo "║                                                       ║"
echo "║   ✓ Community SH installed successfully!             ║"
echo "║                                                       ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo ""
echo -e "${YELLOW}To start Community SH:${NC}"
echo ""
echo "  cd $INSTALL_DIR"
echo "  source venv/bin/activate"
echo "  python manage.py runserver"
echo ""
echo -e "${YELLOW}Then open your browser at:${NC}"
echo "  http://localhost:8000"
echo ""
echo -e "${YELLOW}Login with:${NC}"
echo "  Username: $ADMIN_USER"
echo "  Password: [the password you entered]"
echo ""
echo -e "${GREEN}Happy orchestrating! 🚀${NC}"
echo ""
