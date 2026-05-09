"""Execution model with extended status state machine.

Lifecycle: pending -> cloned -> running -> executed -> completed
Failure paths: * -> failed | * -> timeout
"""

import enum
from datetime import datetime, timezone

from app.extensions import db


class ExecutionStatus(enum.Enum):
    """Execution lifecycle states."""

    PENDING = "pending"
    CLONED = "cloned"
    RUNNING = "running"
    EXECUTED = "executed"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TriggerType(enum.Enum):
    """How the execution was initiated."""

    WEB = "web"
    CRON = "cron"
    API = "api"


class Execution(db.Model):
    """A single test execution run bound to a project and suite."""

    __tablename__ = "executions"

    id = db.Column(db.Integer, primary_key=True)

    # Foreign keys
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
    triggered_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Trigger context
    trigger_type = db.Column(
        db.Enum(TriggerType),
        nullable=False,
        default=TriggerType.WEB,
    )
    extra_args = db.Column(db.Text, nullable=True)

    # Status state machine
    status = db.Column(
        db.Enum(ExecutionStatus),
        nullable=False,
        default=ExecutionStatus.PENDING,
        index=True,
    )

    # Git info
    git_commit_sha = db.Column(db.String(40), nullable=True)

    # Celery info
    celery_task_id = db.Column(db.String(255), nullable=True)

    # Result info
    exit_code = db.Column(db.Integer, nullable=True)
    error_detail = db.Column(db.Text, nullable=True)
    stdout = db.Column(db.Text, nullable=True)
    stderr = db.Column(db.Text, nullable=True)

    # Timestamps
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_sec = db.Column(db.Float, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    project = db.relationship("Project", backref=db.backref("executions", lazy="dynamic"))
    suite = db.relationship("TestSuite", backref=db.backref("executions", lazy="dynamic"))
    trigger_user = db.relationship("User", backref=db.backref("executions", lazy="dynamic"))

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def stage_indicator(self) -> str:
        """Human-readable stage label for the UI timeline."""
        mapping = {
            ExecutionStatus.PENDING: "Queued",
            ExecutionStatus.CLONED: "Git Synced",
            ExecutionStatus.RUNNING: "Running Tests",
            ExecutionStatus.EXECUTED: "Tests Complete",
            ExecutionStatus.COMPLETED: "Report Generated",
            ExecutionStatus.FAILED: "Failed",
            ExecutionStatus.TIMEOUT: "Timed Out",
        }
        return mapping.get(self.status, "Unknown")

    @property
    def is_terminal(self) -> bool:
        """Return True when the execution is in a final state."""
        return self.status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMEOUT,
        )

    @property
    def status_badge_class(self) -> str:
        """Bootstrap colour class for the status badge."""
        mapping = {
            ExecutionStatus.PENDING: "secondary",
            ExecutionStatus.CLONED: "info",
            ExecutionStatus.RUNNING: "primary",
            ExecutionStatus.EXECUTED: "primary",
            ExecutionStatus.COMPLETED: "success",
            ExecutionStatus.FAILED: "danger",
            ExecutionStatus.TIMEOUT: "warning",
        }
        return mapping.get(self.status, "secondary")

    def update_duration(self) -> None:
        """Recompute duration_sec from started_at / finished_at."""
        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            self.duration_sec = round(delta.total_seconds(), 2)

    def __repr__(self) -> str:
        return (
            f"<Execution id={self.id} project={self.project_id} "
            f"status={self.status.value}>"
        )
