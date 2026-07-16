#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this script as a sudo-capable non-root user." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl docker.io docker-compose-v2 openssl ufw
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 8189/udp
sudo ufw allow 8189/tcp
sudo ufw allow 8890/udp

echo "Docker and firewall rules are ready."
echo "Log out and back in once so the docker group membership takes effect."
echo "Only open 8554/tcp or 1935/tcp if RTSP/RTMP clients actually need them."
