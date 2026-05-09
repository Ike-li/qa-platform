"""Celery Beat tasks for nightly dashboard metric aggregation."""

import logging
from datetime import date, timedelta

from app.extensions import celery, db
from app.dashboard.services import aggregate_daily_metrics
from app.models.project import Project

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.metric_tasks.aggregate_all_metrics")
def aggregate_all_metrics():
    """Nightly task: aggregate DashboardMetric for every project for yesterday.

    Designed to run via Celery Beat at 01:00 UTC daily.
    Processes *yesterday* so that all executions for that day are completed.
    """
    target_date = date.today() - timedelta(days=1)
    projects = Project.query.all()

    if not projects:
        logger.info("No projects found; skipping metric aggregation.")
        return

    success_count = 0
    error_count = 0

    for project in projects:
        try:
            aggregate_daily_metrics(project.id, target_date)
            success_count += 1
        except Exception:
            error_count += 1
            logger.exception(
                "Failed to aggregate metrics for project %d on %s",
                project.id, target_date,
            )
            db.session.rollback()

    logger.info(
        "Metric aggregation complete for %s: %d succeeded, %d failed",
        target_date, success_count, error_count,
    )
