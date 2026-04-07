# Deployment

## Architecture

Alaya uses blue-green deployment with Caddy as a reverse proxy.

```
Internet → Caddy (443) → Active Container (8000/8001)
                          Standby Container (off)
```

On deploy:
1. Pull new image from GHCR
2. Start standby container with new image
3. Run Alembic migrations
4. Health check `/health/ready`
5. Swap Caddy upstream to standby
6. Stop old active container

## Prerequisites

### Server Setup (one-time)

1. Install Docker and Caddy on the server
2. Create the network and directories:
   ```bash
   docker network create alaya-net
   mkdir -p /opt/alaya
   ```
3. Create `/opt/alaya/.env` with production environment variables:
   ```
   ALAYA_DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/alaya
   ALAYA_REDIS_URL=redis://redis:6379/0
   ALAYA_ENV=production
   ```
4. Copy `docker/deploy.sh` to `/opt/alaya/deploy.sh`
5. Create `/etc/caddy/upstream` with initial value: `localhost:8000`
6. Configure Caddy to proxy to the upstream file

### GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_SSH_KEY` | SSH private key for the deploy user |
| `DEPLOY_HOST` | Server hostname or IP |
| `DEPLOY_USER` | SSH username (e.g., `deploy`) |

## Manual Deploy

```bash
ssh deploy@server
export GHCR_TOKEN=ghp_...
echo "${GHCR_TOKEN}" | docker login ghcr.io -u USERNAME --password-stdin
/opt/alaya/deploy.sh <commit-sha>
```

## Rollback

```bash
ssh deploy@server
# The previous image is still available locally
docker images ghcr.io/gosync-inc/alaya --format '{{.Tag}}'
/opt/alaya/deploy.sh <previous-sha>
```

## Monitoring

```bash
# Check active container
docker ps --filter name=alaya

# View logs
docker logs -f alaya-blue  # or alaya-green

# Health check
curl https://your-domain.com/health/ready
```
