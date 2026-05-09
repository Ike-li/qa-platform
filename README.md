# QA Platform

Enterprise automated test execution platform with role-based access control, CI/CD integration, Allure reporting, and multi-channel notifications.

## Prerequisites

- **Docker** >= 20.10
- **Docker Compose** >= 2.0

No local Python, MySQL, or Redis installation required -- everything runs in containers.

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> qa-platform && cd qa-platform

# 2. Create your environment file
cp .env.example .env
# Edit .env to set at minimum: SECRET_KEY and FERNET_KEY

# 3. Start all services
docker compose up -d
```

The application will be available at **http://localhost** (via Nginx reverse proxy).

### Default Admin Account

| Field    | Value       |
|----------|-------------|
| Username | `admin`     |
| Password | `admin123`  |

> Change the admin password immediately in production.

To load the default admin and sample data:

```bash
docker compose exec web python scripts/seed_data.py
```

## Architecture

```
                         +-----------+
                         |  Nginx    |  :80 (public)
                         | (reverse  |
                         |  proxy)   |
                         +-----+-----+
                               |
                    +----------+----------+
                    |                     |
              +-----+-----+       /reports/ (Allure)
              |  Flask /   |       static files via
              |  Gunicorn  |       shared volume
              +-----+------+
                    |
        +-----------+-----------+
        |                       |
   +----+----+           +------+-----+
   |  MySQL  |           |   Redis    |
   |  8.0    |           |   7        |
   +---------+           +-----+------+
                               |
                    +----------+----------+
                    |                     |
              +-----+-----+       +------+-----+
              |  Celery    |       |   Celery   |
              |  Worker    |       |   Beat     |
              | (tasks)    |       | (scheduler)|
              +------------+       +------------+
```

**Services:**

| Service  | Role                                              |
|----------|---------------------------------------------------|
| `web`    | Flask application served by Gunicorn              |
| `nginx`  | Reverse proxy, static file server for Allure      |
| `mysql`  | Primary database                                  |
| `redis`  | Celery message broker and result backend          |
| `worker` | Celery worker for async test execution            |
| `beat`   | Celery beat scheduler for cron-triggered tests    |

## Configuration Reference

All configuration is via environment variables in `.env`:

### Flask

| Variable        | Default                  | Description                          |
|-----------------|--------------------------|--------------------------------------|
| `FLASK_ENV`     | `development`            | Environment: development / testing / production |
| `FLASK_APP`     | `manage.py`              | Flask application entry point        |
| `SECRET_KEY`    | `change-me`              | Flask secret key (required, change in production) |
| `FERNET_KEY`    |                          | Fernet encryption key for git credentials (required) |

### Database

| Variable            | Default                                      | Description        |
|---------------------|----------------------------------------------|--------------------|
| `MYSQL_HOST`        | `mysql`                                      | MySQL host         |
| `MYSQL_PORT`        | `3306`                                       | MySQL port         |
| `MYSQL_ROOT_PASSWORD` | `rootpass`                                | MySQL root pass    |
| `MYSQL_DATABASE`    | `qaplatform`                                 | Database name      |
| `MYSQL_USER`        | `qauser`                                     | Database user      |
| `MYSQL_PASSWORD`    | `qapass`                                     | Database password  |
| `DATABASE_URL`      | `mysql+pymysql://qauser:qapass@mysql:3306/qaplatform` | SQLAlchemy URI |

### Redis / Celery

| Variable              | Default                       | Description                |
|-----------------------|-------------------------------|----------------------------|
| `REDIS_HOST`          | `redis`                       | Redis host                 |
| `REDIS_PORT`          | `6379`                        | Redis port                 |
| `CELERY_BROKER_URL`   | `redis://redis:6379/0`        | Celery broker URL          |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1`      | Celery result backend      |

### Allure Reporting

| Variable              | Default              | Description                     |
|-----------------------|----------------------|---------------------------------|
| `ALLURE_REPORTS_DIR`  | `/app/allure-reports`| Path to generated Allure HTML   |
| `ALLURE_RESULTS_DIR`  | `/app/allure-results`| Path to Allure raw results      |

### SMTP (Notifications)

| Variable        | Default              | Description               |
|-----------------|----------------------|---------------------------|
| `SMTP_HOST`     | `localhost`          | SMTP server host          |
| `SMTP_PORT`     | `587`                | SMTP server port          |
| `SMTP_USER`     |                      | SMTP auth username        |
| `SMTP_PASSWORD`  |                      | SMTP auth password       |
| `SMTP_FROM`     | `noreply@...`        | Sender email address      |

## User Roles & Permissions

| Permission         | super_admin | project_lead | tester | visitor |
|--------------------|:-----------:|:------------:|:------:|:-------:|
| `user.manage`      | Yes         |              |        |         |
| `project.create`   | Yes         | Yes          |        |         |
| `project.edit`     | Yes         | Yes          |        |         |
| `project.delete`   | Yes         |              |        |         |
| `execution.trigger`| Yes         | Yes          | Yes    |         |
| `execution.view`   | Yes         | Yes          | Yes    | Yes     |
| `report.view`      | Yes         | Yes          | Yes    | Yes     |
| `config.manage`    | Yes         |              |        |         |
| `audit.view`       | Yes         |              |        |         |

## API Documentation

All API endpoints are under the `/api/v1` prefix and require Bearer token authentication.

### Authentication

Generate an API token from the admin UI or via the CLI. Pass it as:

```
Authorization: Bearer qap_<token>
```

### Endpoints

#### GET /api/v1/projects

List all projects.

```bash
curl -H "Authorization: Bearer qap_<token>" http://localhost/api/v1/projects
```

Response:
```json
{
  "projects": [
    {
      "id": 1,
      "name": "My Project",
      "git_url": "https://github.com/org/repo.git",
      "git_branch": "main",
      "repo_path": "/data/repos/1"
    }
  ]
}
```

#### GET /api/v1/projects/:id

Get a single project with suites and cron schedules.

```bash
curl -H "Authorization: Bearer qap_<token>" http://localhost/api/v1/projects/1
```

#### POST /api/v1/executions

Trigger a new test execution.

```bash
curl -X POST \
  -H "Authorization: Bearer qap_<token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id": 1, "extra_args": "-k smoke"}' \
  http://localhost/api/v1/executions
```

Response (201):
```json
{
  "execution_id": 1,
  "status": "pending",
  "project_id": 1,
  "suite_id": null,
  "celery_task_id": "abc-123"
}
```

Rate limit: 10 requests per minute per token.

#### GET /health

Health check endpoint (no auth required).

```bash
curl http://localhost/health
```

Response:
```json
{"status": "ok"}
```

## Development

### Running locally (without Docker)

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set environment
export FLASK_ENV=development
export DATABASE_URL=sqlite:///dev.db
export CELERY_BROKER_URL=redis://localhost:6379/0

# Initialize database
flask db upgrade

# Seed data
python scripts/seed_data.py

# Run development server
flask run --debug

# Run tests
pytest tests/ -v
```

### Running Tests

```bash
# Inside Docker
docker compose exec web pytest tests/ -v

# Locally (requires pytest-flask)
pip install pytest pytest-flask
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=term-missing
```

### Database Migrations

```bash
# Create a new migration
flask db migrate -m "description"

# Apply migrations
flask db upgrade

# Rollback
flask db downgrade
```

### Seed Data

The seed script creates a default admin user and sample project:

```bash
python scripts/seed_data.py
# Creates: admin / admin123, sample project, daily cron schedule
```

The script refuses to run in production (`FLASK_ENV=production`).

## Production Deployment

### Starting in production mode

```bash
cp .env.example .env
# Edit .env: set FLASK_ENV=production, strong SECRET_KEY, generate FERNET_KEY

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The production compose override adds:
- `restart: always` for all services
- Memory and CPU resource limits
- JSON-file log driver with rotation (10MB max, 3 files)
- Access logging enabled for Gunicorn

### Generating a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into your `.env` as `FERNET_KEY`.

### Health Monitoring

The `/health` endpoint returns `{"status": "ok"}` when the application is running. The Dockerfile includes a built-in `HEALTHCHECK` directive.

### Backups

Back up the MySQL volume regularly:

```bash
docker compose exec mysql mysqldump -u root -p qaplatform > backup.sql
```

## Project Structure

```
qa-platform/
+-- app/
|   +-- __init__.py          # Application factory
|   +-- extensions.py        # Flask extension instances
|   +-- models/              # SQLAlchemy models
|   +-- auth/                # Authentication blueprint
|   +-- admin/               # Admin panel (user management, config)
|   +-- projects/            # Project CRUD with git integration
|   +-- executions/          # Test execution triggering
|   +-- dashboard/           # Metrics visualization
|   +-- notifications/       # Notification config and delivery
|   +-- api/                 # REST API (token-authenticated)
|   +-- tasks/               # Celery tasks and scheduler
|   +-- utils/               # Shared utilities (audit, errors, decorators)
|   +-- templates/           # Jinja2 templates
|   +-- static/              # Static assets
+-- tests/                   # Test suite
+-- scripts/                 # Utility scripts (seed data)
+-- nginx/                   # Nginx configuration
+-- config.py                # Configuration classes
+-- manage.py                # Flask CLI entry point
+-- requirements.txt         # Python dependencies
+-- Dockerfile               # Multi-stage production build
+-- docker-compose.yml       # Base compose file
+-- docker-compose.prod.yml  # Production overrides
+-- .env.example             # Environment template
+-- .gitignore               # Git ignore rules
```
