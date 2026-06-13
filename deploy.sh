#!/bin/bash
# Agency42 VPS Deployment Script
# Usage: scp this entire project to the server, then run this script.
# Example:
#   scp -r /path/to/project root@162.251.147.16:/root/agency42
#   ssh root@162.251.147.16 "cd /root/agency42 && bash deploy.sh"

set -e

echo "=== Agency42 Deployment ==="

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "[1/4] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "[1/4] Docker already installed."
fi

# 2. Install Docker Compose plugin if not present
if ! docker compose version &> /dev/null 2>&1; then
    echo "[2/4] Installing Docker Compose plugin..."
    apt-get update -qq && apt-get install -y docker-compose-plugin
    echo "Docker Compose installed."
else
    echo "[2/4] Docker Compose already available."
fi

# 3. Check .env file
if [ ! -f .env ]; then
    echo "[3/4] ERROR: .env file not found!"
    echo "Create .env file first. Example:"
    echo ""
    cat .env.example
    echo ""
    echo "Run: cp .env.example .env && nano .env"
    exit 1
else
    echo "[3/4] .env file found."
fi

# 4. Build and start
echo "[4/4] Building and starting Agency42..."
docker compose down 2>/dev/null || true
docker compose up -d --build

echo ""
echo "=== Deployment Complete ==="
echo "Admin panel: http://$(hostname -I | awk '{print $1}'):8000/agency/"
echo "Logs: docker compose logs -f"
echo ""
docker compose ps
