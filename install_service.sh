#!/bin/bash

# ==========================================
# NEURODASH - AUTO INSTALLER (Ubuntu/Linux)
# ==========================================

set -e # Stop on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}⚡ Configuring NeuroDash system service...${NC}"

# 1. Detect paths and user
PROJECT_DIR=$(pwd)
CURRENT_USER=$(whoami)
UV_PATH=$(which uv)

if [ -z "$UV_PATH" ]; then
    echo -e "${RED}❌ Error: 'uv' not found in PATH.${NC}"
    echo "   Please ensure 'uv' is installed and your shell is restarted."
    exit 1
fi

SERVICE_FILE="/tmp/neurodash.service"

echo "   - Directory: $PROJECT_DIR"
echo "   - User:      $CURRENT_USER"
echo "   - uv Path:   $UV_PATH"

# 2. Generate temporary systemd unit file
cat <<EOF > $SERVICE_FILE
[Unit]
Description=NeuroDash AI Workstation Monitor
After=network.target

[Service]
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=/usr/bin:/usr/local/bin"
# Executing via absolute path to uv
ExecStart=$UV_PATH run gunicorn -w 1 --threads 4 --worker-class gthread -b 0.0.0.0:9999 main:app

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 3. Install with root privileges
echo -e "${YELLOW}🔑 Installing systemd service (sudo password required)...${NC}"

sudo mv $SERVICE_FILE /etc/systemd/system/neurodash.service
sudo chown root:root /etc/systemd/system/neurodash.service
sudo chmod 644 /etc/systemd/system/neurodash.service

# 4. Enable and Start
echo "🔄 Reloading systemd daemon..."
sudo systemctl daemon-reload
echo "✅ Enabling service on boot..."
sudo systemctl enable neurodash.service
echo "🚀 Starting NeuroDash..."
sudo systemctl restart neurodash.service

echo -e "${GREEN}✅ SUCCESS! NeuroDash is running in the background.${NC}"
echo "   - View logs:   sudo journalctl -u neurodash -f"
echo "   - Dashboard:   http://localhost:9999"