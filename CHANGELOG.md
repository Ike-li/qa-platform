# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-05-09

### Added

#### Core
- Flask application factory pattern with blueprint architecture
- MySQL 8.0 database with SQLAlchemy ORM (14 tables)
- Docker Compose deployment (6 containers: nginx, web, worker, beat, mysql, redis)
- Nginx reverse proxy with Allure report static serving and SPA fallback

#### Authentication & Authorization
- 4-role RBAC system (super_admin, project_lead, tester, visitor) based on TestRail model
- Login/logout with session management (Flask-Login)
- Permission matrix with `@role_required` and `@permission_required` decorators
- API token authentication (SHA-256 hashed, with expiry and revocation)

#### Test Execution
- 3-stage chained Celery pipeline: git_sync → run_tests → generate_report
- Virtual environment isolation per execution (prevents dependency conflicts)
- JUnit XML parsing for test result extraction
- Allure report generation served via nginx at `/reports/{execution_id}/`
- Checkpointed status tracking (pending → cloned → running → executed → completed)
- Redis-based distributed lock for concurrent execution control
- Per-stage configurable timeouts

#### Project Management
- Project CRUD with Git repository integration
- Generic Git support (any Git service via URL + credentials)
- Fernet-encrypted credential storage for private repositories
- Automatic test suite discovery (scans for `test_*.py` files)

#### Dashboard
- Pass rate overview (doughnut chart)
- Trend analysis (daily/weekly/monthly line chart)
- Execution queue status (live table with auto-refresh)
- Failed test quick-view with Allure report links
- Chart.js rendering with project filter

#### Triggers
- Web manual trigger
- Cron scheduling via custom DatabaseScheduler (dynamic MySQL-backed)
- REST API trigger with rate limiting (10 req/min per token)

#### Notifications
- Email (SMTP)
- DingTalk webhook
- WeChat Work webhook
- Configurable per-project, per-channel
- Idempotent delivery with NotificationLog

#### Audit & Admin
- Full audit logging (account, execution, project management operations)
- Admin-configurable system settings (timeout, parallel count, retention)
- Data retention cleanup (configurable per entity type)
- Audit log viewer with filters (user, action, type, date range)

#### Security
- Secret key enforcement (fails fast if not configured)
- Fernet encryption for sensitive credentials
- CSRF protection on all forms (Flask-WTF)
- Login rate limiting (5 attempts/min/IP via Redis)
- API execution RBAC permission check
- Extra_args whitelist validation (prevents command injection)
- Rollback protection on all database commits
- Non-root Docker user

#### Testing
- 117 test cases covering auth, projects, executions, RBAC, notifications, API
- Pytest fixtures with per-test database isolation
- Role-parametrized RBAC tests

#### Documentation
- README.md with quick start, architecture, configuration reference
- Wiki (5 pages): architecture, RBAC, execution pipeline, deployment, API
- CONTRIBUTING.md with development guidelines
- .env.example with all configuration variables

### Technical Decisions
- Monolithic Flask application (chosen over React SPA and Django)
- nginx from Day 1 for Allure report serving (not Flask)
- Custom DatabaseScheduler for dynamic cron (not celery-redbeat)
- Chained Celery tasks with per-stage timeouts (not monolithic task)
- Virtual environment per execution (not Docker-in-Docker)
- Redis distributed lock (not threading semaphore)
