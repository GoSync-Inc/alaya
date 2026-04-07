#!/usr/bin/env bash
set -euo pipefail

# Usage: deploy.sh <image_tag>
# Expects: GHCR_TOKEN env var for docker login

IMAGE_TAG="${1:?Usage: deploy.sh <image_tag>}"
IMAGE="ghcr.io/gosync-inc/alaya:${IMAGE_TAG}"
CONTAINER_BLUE="alaya-blue"
CONTAINER_GREEN="alaya-green"
CADDY_CONFIG="/etc/caddy/Caddyfile"

echo "=== Deploying ${IMAGE} ==="

# Determine active/standby
if docker ps --format '{{.Names}}' | grep -q "${CONTAINER_BLUE}"; then
    ACTIVE="${CONTAINER_BLUE}"
    STANDBY="${CONTAINER_GREEN}"
    STANDBY_PORT=8001
else
    ACTIVE="${CONTAINER_GREEN}"
    STANDBY="${CONTAINER_BLUE}"
    STANDBY_PORT=8000
fi

echo "Active: ${ACTIVE}, deploying to: ${STANDBY}"

# Pull new image
docker pull "${IMAGE}"

# Stop standby if running
docker rm -f "${STANDBY}" 2>/dev/null || true

# Start standby with new image
docker run -d \
    --name "${STANDBY}" \
    --env-file /opt/alaya/.env \
    --network alaya-net \
    -p "${STANDBY_PORT}:8000" \
    --restart unless-stopped \
    "${IMAGE}"

# Run migrations
if ! docker exec "${STANDBY}" uv run alembic upgrade head; then
    echo "ERROR: Migration failed. Removing standby container."
    docker rm -f "${STANDBY}"
    exit 1
fi

# Health check (up to 30 seconds)
echo "Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${STANDBY_PORT}/health/ready" > /dev/null 2>&1; then
        echo "Health check passed on attempt ${i}"
        break
    fi
    if [ "${i}" -eq 30 ]; then
        echo "ERROR: Health check failed after 30 attempts"
        docker rm -f "${STANDBY}"
        exit 1
    fi
    sleep 1
done

# Swap Caddy upstream — rewrite reverse_proxy target in Caddyfile
sed -i "s|reverse_proxy localhost:[0-9]*|reverse_proxy localhost:${STANDBY_PORT}|" "${CADDY_CONFIG}"
caddy reload --config "${CADDY_CONFIG}" 2>/dev/null || systemctl reload caddy

# Stop old container
docker rm -f "${ACTIVE}" 2>/dev/null || true

echo "=== Deploy complete: ${STANDBY} is now active ==="
