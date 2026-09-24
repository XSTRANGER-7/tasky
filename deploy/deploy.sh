#!/usr/bin/env bash
# Build and (re)start the Tasky backend on the EC2 server. Run from ~/tasky:
#
#   bash deploy/deploy.sh            build the image from ./backend and start everything
#   bash deploy/deploy.sh --no-build restart with the image already built
#
# Safe to re-run: containers are replaced one by one, migrations run on API start, and
# the previous image is kept as tasky-api:previous for a quick rollback:
#   TAG=previous docker compose -f docker-compose.ec2.yml up -d --no-build
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.ec2.yml"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ -f .env ]] || die ".env is missing. cp deploy/.env.production.example .env, fill it in, chmod 600 .env"
[[ -d backend ]] || die "backend/ is missing. Upload the code first (see docs/deploy-ec2.md)."
grep -q '^API_DOMAIN=.\+' .env || die "API_DOMAIN is empty in .env"
# Unfilled placeholders look like <...> without an @ (a real "Name <me@x.com>" is fine).
if grep -qE '<[^@>]*>' .env; then
  grep -nE '<[^@>]*>' .env | sed 's/=.*/=<...>/' >&2
  die "Some values in .env still contain <placeholders> (listed above)."
fi
[[ $(stat -c %a .env) == 600 ]] || { chmod 600 .env && echo "(set .env to chmod 600)"; }

if [[ "${1:-}" != "--no-build" ]]; then
  if docker image inspect tasky-api:latest >/dev/null 2>&1; then
    docker tag tasky-api:latest tasky-api:previous
  fi
  log "Building the backend image (first build takes a few minutes)"
  GIT_SHA="$(date +%Y%m%d-%H%M)" $COMPOSE build --pull
fi

log "Starting api, worker and caddy"
$COMPOSE up -d --remove-orphans

log "Waiting for the API to report healthy"
for i in $(seq 1 40); do
  status="$(docker inspect -f '{{.State.Health.Status}}' "$($COMPOSE ps -q api)" 2>/dev/null || echo starting)"
  [[ "$status" == healthy ]] && break
  sleep 3
done
[[ "$status" == healthy ]] || { $COMPOSE logs --tail 60 api; die "API is not healthy (logs above)."; }

log "Containers"
$COMPOSE ps

DOMAIN="$(grep '^API_DOMAIN=' .env | cut -d= -f2-)"
log "Public health check: https://${DOMAIN}/health"
if curl -fsS --max-time 20 "https://${DOMAIN}/health"; then
  printf '\n\nTasky backend is live at https://%s\n' "$DOMAIN"
else
  cat <<EOF

The API is healthy inside the server, but https://${DOMAIN} did not answer yet. Usually:
  - the domain does not point at this server's Elastic IP yet (DNS can take minutes), or
  - ports 80/443 are not open in the EC2 security group.
Caddy retries the certificate automatically; watch it with:
  $COMPOSE logs -f caddy
EOF
fi

log "Cleaning up old build layers"
docker image prune -f >/dev/null
