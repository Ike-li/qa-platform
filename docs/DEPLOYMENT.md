# Production Deployment Guide

## Prerequisites

- Docker 24+ and Docker Compose v2
- A server with at least 4GB RAM
- Domain name (for HTTPS)

## First-Time Setup

### 1. Clone the repository

```bash
git clone <repo-url> /opt/qa-platform
cd /opt/qa-platform
```

### 2. Generate secrets

```bash
# Generate all required secrets
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
MYSQL_ROOT_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
MYSQL_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

# Create .env file
cat > .env << EOF
FLASK_ENV=production
SECRET_KEY=${SECRET_KEY}
FERNET_KEY=${FERNET_KEY}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
MYSQL_DATABASE=qaplatform
MYSQL_USER=qauser
MYSQL_PASSWORD=${MYSQL_PASSWORD}
DATABASE_URL=mysql+pymysql://qauser:${MYSQL_PASSWORD}@mysql:3306/qaplatform
TEST_DATABASE_URL=sqlite:///:memory:
REDIS_PASSWORD=${REDIS_PASSWORD}
CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/1
ENABLE_SANDBOX=false
EOF
```

### 3. Start services

```bash
docker compose -f docker-compose.prod.yml up -d
```

The web service runs `flask db upgrade` automatically via `docker-entrypoint.sh` before starting gunicorn.

### 4. Create admin user

```bash
docker compose exec web flask create-admin admin admin@example.com
```

## Existing Database Migration

If you have an existing database with tables but no Alembic migration history:

```bash
docker compose exec web flask db stamp head
```

Then future upgrades will use `flask db upgrade` normally.

## Fernet Key Migration

If changing from the old `SECRET_KEY`-derived Fernet key to a dedicated `FERNET_KEY`:

1. Set the new `FERNET_KEY` in `.env`
2. Before restarting, re-encrypt any stored encrypted values (e.g., SMTP password in SystemConfig, git credentials in projects)
3. Restart services: `docker compose -f docker-compose.prod.yml up -d`

## Sandbox Mode

To enable isolated test execution in Docker containers:

1. Build the sandbox image:
```bash
docker build -f Dockerfile.sandbox -t qa-platform-sandbox:latest .
```

2. Set in `.env`:
```
ENABLE_SANDBOX=true
```

3. Restart the worker:
```bash
docker compose -f docker-compose.prod.yml restart worker
```

The sandbox runs tests in isolated containers with:
- Read-only filesystem
- Network disabled by default
- 512MB memory limit
- 0.5 CPU limit

Per-project network access can be enabled via the `sandbox_network` column on the Project model.

## HTTPS Setup

1. Place SSL certificates in `nginx/ssl/`:
```bash
mkdir -p nginx/ssl
cp /path/to/cert.pem nginx/ssl/
cp /path/to/key.pem nginx/ssl/
```

2. Edit `nginx/nginx.conf`:
- Uncomment the HTTPS server block
- Uncomment the HTTP→HTTPS redirect
- Uncomment the HSTS header

3. Restart nginx:
```bash
docker compose -f docker-compose.prod.yml restart nginx
```

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `FLASK_ENV` | Yes | `production` for prod |
| `SECRET_KEY` | Yes | 32+ char random hex string |
| `FERNET_KEY` | Yes | Fernet key for credential encryption |
| `MYSQL_ROOT_PASSWORD` | Yes | MySQL root password |
| `MYSQL_PASSWORD` | Yes | MySQL app user password |
| `DATABASE_URL` | Yes | SQLAlchemy database URI |
| `REDIS_PASSWORD` | Yes | Redis authentication password |
| `CELERY_BROKER_URL` | Yes | Redis URL for Celery broker |
| `CELERY_RESULT_BACKEND` | Yes | Redis URL for Celery results |
| `ENABLE_SANDBOX` | No | `true` to enable sandbox execution (default: `false`) |
| `SANDBOX_IMAGE` | No | Sandbox Docker image (default: `qa-platform-sandbox:latest`) |
| `SANDBOX_MEMORY_LIMIT` | No | Container memory limit (default: `512m`) |
| `SANDBOX_CPU_QUOTA` | No | CPU quota in microseconds (default: `50000` = 0.5 CPU) |

## Backup

```bash
# Database
docker compose exec mysql mysqldump -u root -p qaplatform > backup.sql

# Allure reports
docker cp $(docker compose ps -q web):/app/allure-reports ./backup-reports/
```
