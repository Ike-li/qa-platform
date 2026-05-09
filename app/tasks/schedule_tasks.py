"""Celery task for executing scheduled (cron) test runs."""

import logging

from app.extensions import celery, db

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.schedule_tasks.run_cron_schedule", bind=True, max_retries=1)
def run_cron_schedule(self, schedule_id: int) -> None:
    """Execute a scheduled test run.

    Called by Celery Beat via DatabaseScheduler when a CronSchedule
    entry fires. Loads the schedule, creates an execution record,
    and dispatches the execution pipeline.
    """
    from app.models.cron_schedule import CronSchedule
    from app.models.execution import Execution, ExecutionStatus, TriggerType
    from app.executions.services import prepare_execution
    from app.tasks.execution_tasks import run_execution_pipeline

    try:
        schedule = db.session.get(CronSchedule, schedule_id)
        if not schedule:
            logger.warning("CronSchedule %d not found, skipping", schedule_id)
            return

        if not schedule.is_active:
            logger.info("CronSchedule %d is inactive, skipping", schedule_id)
            return

        # Create execution record
        execution = prepare_execution(
            project_id=schedule.project_id,
            suite_id=schedule.suite_id,
            triggered_by=None,  # System-triggered
            trigger_type=TriggerType.CRON,
        )

        # Dispatch execution pipeline
        run_execution_pipeline.delay(execution.id)

        # Update last_run timestamp
        from datetime import datetime, timezone
        schedule.last_run = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(
            "Cron execution dispatched: schedule=%d, execution=%d, project=%d",
            schedule_id, execution.id, schedule.project_id,
        )

    except Exception:
        logger.exception("Failed to execute cron schedule %d", schedule_id)
        db.session.rollback()
        raise
