"""Celery application entry point.

Imports and calls the Flask app factory so that _configure_celery applies
FlaskTask to the canonical Celery instance in app.extensions. Then re-exports
that single instance so docker-compose ``-A app.tasks.celery_app`` resolves
to the same object used throughout the application.
"""

from app import create_app  # noqa: F401 — triggers _configure_celery

# create_app() already called _configure_celery(app) which:
# 1. Updates celery.conf from Flask config
# 2. Sets celery.Task = FlaskTask (app context in every task)
# 3. Calls celery.autodiscover_tasks(["app.tasks"])

from app.extensions import celery  # noqa: F401 — re-export the canonical instance
