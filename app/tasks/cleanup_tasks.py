"""Celery tasks for periodic data retention cleanup.

Registered as a Celery Beat task that runs once per day.
"""

import logging

from app.extensions import celery

logger = logging.getLogger(__name__)


@celery.task(
    name="app.tasks.cleanup_tasks.enforce_retention",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def enforce_retention(self):
    """Delete old executions, reports, and audit logs per SystemConfig retention settings.

    Reads retention.* config keys and removes rows older than the configured
    number of days.  Allure report files on disk are also deleted.

    Expected to be scheduled via Celery Beat to run once daily.
    """
    try:
        from app.admin.services import enforce_retention as _enforce

        result = _enforce()
        logger.info(
            "Retention cleanup complete – executions=%d, reports=%d, audit=%d",
            result["executions_deleted"],
            result["reports_deleted"],
            result["audit_deleted"],
        )
        return result
    except Exception as exc:
        logger.exception("Retention cleanup failed: %s", exc)
        raise self.retry(exc=exc)
