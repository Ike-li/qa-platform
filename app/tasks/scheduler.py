"""Dynamic Celery Beat scheduler backed by MySQL CronSchedule table.

Replaces the Phase 0 stub. Reads schedules from the database on a
configurable interval (default 5 seconds), so changes made via the
admin UI take effect without restarting the beat process.
"""

import logging
import time

from celery.beat import Scheduler, ScheduleEntry
from celery.schedules import crontab as celery_crontab

logger = logging.getLogger(__name__)

# Default refresh interval in seconds
DEFAULT_REFRESH_INTERVAL = 5


class DatabaseScheduler(Scheduler):
    """Celery Beat scheduler that reads CronSchedule rows from MySQL."""

    _schedule = {}
    _last_refresh = 0.0
    _refresh_interval = DEFAULT_REFRESH_INTERVAL

    def setup_schedule(self):
        """Initialize schedule on startup."""
        self._schedule = {}
        self._last_refresh = 0.0
        self._load_from_db()

    @property
    def schedule(self):
        """Return current schedule, refreshing from DB if interval elapsed."""
        now = time.time()
        if now - self._last_refresh >= self._refresh_interval:
            self._load_from_db()
        return self._schedule

    def _load_from_db(self):
        """Load active CronSchedule entries from MySQL.

        Uses Flask app context for SQLAlchemy. Falls back to cached
        schedule on DB errors to prevent beat from crashing.
        """
        self._last_refresh = time.time()

        try:
            from flask import current_app
            app = current_app._get_current_object()
        except RuntimeError:
            # No Flask app context available (e.g., during tests)
            logger.debug("No Flask app context, using cached schedule")
            return

        try:
            with app.app_context():
                from app.models.cron_schedule import CronSchedule

                schedules = CronSchedule.query.filter_by(is_active=True).all()
                new_schedule = {}

                for s in schedules:
                    entry_name = f"cron_schedule_{s.id}"
                    try:
                        cron = s.celery_schedule
                    except (ValueError, AttributeError) as exc:
                        logger.warning(
                            "Invalid cron expression for schedule %d: %s (%s)",
                            s.id, s.cron_expr, exc,
                        )
                        continue

                    new_schedule[entry_name] = ScheduleEntry(
                        name="app.tasks.schedule_tasks.run_cron_schedule",
                        schedule=cron,
                        args=(s.id,),
                        kwargs={},
                        options={},
                        app=self.app,
                    )

                self._schedule = new_schedule
                logger.debug("Loaded %d schedules from database", len(new_schedule))

        except Exception:
            logger.exception("Failed to load schedules from database, using cached")
            # Keep existing self._schedule unchanged

