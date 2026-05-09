"""CronSchedule model for periodic test execution triggers.

Stores cron expressions per project/suite pair and converts them
to Celery crontab schedules for the DatabaseScheduler.
"""

import re
from datetime import datetime, timezone

from celery.schedules import crontab as celery_crontab

from app.extensions import db

# Regex: supports standard 5-field cron plus */N step syntax
_CRON_RE = re.compile(
    r"^(?P<minute>[0-9*/,\-]+)\s+"
    r"(?P<hour>[0-9*/,\-]+)\s+"
    r"(?P<day>[0-9*/,\-]+)\s+"
    r"(?P<month>[0-9*/,\-]+)\s+"
    r"(?P<weekday>[0-9*/,\-]+)$"
)


def _parse_field(raw: str, low: int, high: int) -> list:
    """Parse a single cron field into a list of integer values.

    Handles: *, */N, N, N-M, N,M, and combinations.
    """
    values: set[int] = set()
    for part in raw.split(","):
        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
        else:
            range_part = part

        if range_part == "*":
            start, end = low, high
        elif "-" in range_part:
            start_str, end_str = range_part.split("-", 1)
            start, end = int(start_str), int(end_str)
        else:
            start = end = int(range_part)

        for v in range(start, end + 1, step):
            if low <= v <= high:
                values.add(v)

    return sorted(values) if values else list(range(low, high + 1))


class CronSchedule(db.Model):
    """A periodic schedule linking a project (and optional suite) to a cron expression."""

    __tablename__ = "cron_schedules"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suite_id = db.Column(
        db.Integer,
        db.ForeignKey("test_suites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    cron_expr = db.Column(db.String(64), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_run = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = db.relationship(
        "Project",
        backref=db.backref("cron_schedules", lazy="dynamic", cascade="all, delete-orphan"),
    )
    suite = db.relationship(
        "TestSuite",
        backref=db.backref("cron_schedules", lazy="dynamic"),
    )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_cron_expr(expr: str) -> bool:
        """Return True if *expr* is a valid 5-field cron expression.

        Supports standard cron syntax including ``*/N`` step values.
        """
        if not expr or not isinstance(expr, str):
            return False
        expr = expr.strip()
        match = _CRON_RE.match(expr)
        if not match:
            return False
        # Validate each field parses without error
        try:
            _parse_field(match.group("minute"), 0, 59)
            _parse_field(match.group("hour"), 0, 23)
            _parse_field(match.group("day"), 1, 31)
            _parse_field(match.group("month"), 1, 12)
            _parse_field(match.group("weekday"), 0, 6)
            return True
        except (ValueError, IndexError):
            return False

    # ------------------------------------------------------------------
    # Celery schedule conversion
    # ------------------------------------------------------------------

    @property
    def celery_schedule(self):
        """Parse *cron_expr* into a :class:`celery.schedules.crontab`.

        Returns ``None`` if the expression is invalid.
        """
        match = _CRON_RE.match(self.cron_expr.strip())
        if not match:
            return None

        try:
            minutes = ",".join(str(v) for v in _parse_field(match.group("minute"), 0, 59))
            hours = ",".join(str(v) for v in _parse_field(match.group("hour"), 0, 23))
            days = ",".join(str(v) for v in _parse_field(match.group("day"), 1, 31))
            months = ",".join(str(v) for v in _parse_field(match.group("month"), 1, 12))
            weekdays = ",".join(str(v) for v in _parse_field(match.group("weekday"), 0, 6))

            return celery_crontab(
                minute=minutes,
                hour=hours,
                day_of_month=days,
                month_of_year=months,
                day_of_week=weekdays,
            )
        except Exception:
            return None

    def __repr__(self) -> str:
        return (
            f"<CronSchedule id={self.id} project={self.project_id} "
            f"cron={self.cron_expr!r} active={self.is_active}>"
        )
