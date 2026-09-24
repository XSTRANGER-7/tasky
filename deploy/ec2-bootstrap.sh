#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 24.04 EC2 instance (t3.small recommended).
# Idempotent: safe to re-run.
#
#   scp deploy/ec2-bootstrap.sh ubuntu@<elastic-ip>:~ && ssh ubuntu@<elastic-ip> 'sudo bash ec2-bootstrap.sh'
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "run as root: sudo bash $0" >&2
  exit 1
fi

APP_USER="${APP_USER:-ubuntu}"
APP_DIR="/home/${APP_USER}/tasky"
SWAP_FILE=/swapfile

log() { printf '\n==> %s\n' "$*"; }

# Ubuntu mirrors sometimes replace a package between "update" and the download, which
# fails with "404 Not Found". Refresh the package list and try again (up to 3 times).
apt_retry() {
  for attempt in 1 2 3; do
    apt-get update -y && apt-get "$@" && return 0
    echo "apt-get $1 failed (attempt ${attempt}/3); refreshing the package list and retrying" >&2
    sleep 10
  done
  return 1
}

log "System update"
export DEBIAN_FRONTEND=noninteractive
apt_retry upgrade -y --fix-missing
apt_retry install -y ca-certificates curl gnupg git unattended-upgrades

log "Docker Engine + compose plugin (official apt repository)"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt_retry install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$APP_USER"
systemctl enable --now docker

log "Docker daemon defaults: rotate logs so the 20 GB disk never fills"
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
  systemctl restart docker
fi

log "2 GB swap (headroom for image builds on small instances)"
if ! swapon --show | grep -q "$SWAP_FILE"; then
  fallocate -l 2G "$SWAP_FILE"
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE"
  swapon "$SWAP_FILE"
  grep -q "$SWAP_FILE" /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
  sysctl -w vm.swappiness=10
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

log "Automatic security updates"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades

log "SSH hardening: key-only, no root login"
cat > /etc/ssh/sshd_config.d/99-incident-desk.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
# Ubuntu 24.04 starts SSH on demand (ssh.socket), so ssh.service may not be running;
# then the new settings simply apply to the next connection.
systemctl try-reload-or-restart ssh 2>/dev/null || true

log "App directory"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$APP_DIR" "$APP_DIR/deploy"

cat <<EOF

Bootstrap complete. Log out and back in (for the docker group), then as ${APP_USER}:
  1. Upload the code into ${APP_DIR}  (docs/deploy-ec2.md, step 6)
  2. cd ${APP_DIR} && cp deploy/.env.production.example .env && nano .env && chmod 600 .env
  3. bash deploy/deploy.sh
  4. curl -fsS https://\$API_DOMAIN/health
EOF
