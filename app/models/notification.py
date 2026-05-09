"""Notification models: channel configuration and delivery log.

NotificationConfig stores per-project notification preferences.
NotificationLog records each delivery attempt.
"""

import enum
from datetime import datetime, timezone

from app.extensions import db


class NotificationChannel(enum.Enum):
    """Supported notification channels."""

    EMAIL = "email"
    DINGTALK = "dingtalk"
    WECHAT = "wechat"


class NotificationDeliveryStatus(enum.Enum):
    """Delivery attempt outcomes."""

    SENT = "sent"
    FAILED = "failed"


class NotificationConfig(db.Model):
    """Per-project notification channel configuration."""

    __tablename__ = "notification_configs"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel = db.Column(
        db.Enum(NotificationChannel),
        nullable=False,
    )

    webhook_url = db.Column(db.String(1024), nullable=True)
    email_recipients = db.Column(db.Text, nullable=True)  # comma-separated emails
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # JSON list of event names that trigger this notification, e.g.
    # ["execution.completed", "execution.failed"]
    trigger_events = db.Column(db.JSON, nullable=False, default=list)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = db.relationship(
        "Project",
        backref=db.backref("notification_configs", lazy="dynamic", cascade="all, delete-orphan"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationConfig id={self.id} project={self.project_id} "
            f"channel={self.channel.value}>"
        )


class NotificationLog(db.Model):
    """Record of a single notification delivery attempt."""

    __tablename__ = "notification_logs"
    __table_args__ = (
        db.UniqueConstraint("execution_id", "channel", name="uq_notif_log_exec_channel"),
    )

    id = db.Column(db.Integer, primary_key=True)

    execution_id = db.Column(
        db.Integer,
        db.ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_id = db.Column(
        db.Integer,
        db.ForeignKey("notification_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    channel = db.Column(
        db.Enum(NotificationChannel),
        nullable=False,
    )
    status = db.Column(
        db.Enum(NotificationDeliveryStatus),
        nullable=False,
        default=NotificationDeliveryStatus.SENT,
    )
    error_msg = db.Column(db.Text, nullable=True)
    sent_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    execution = db.relationship(
        "Execution",
        backref=db.backref("notification_logs", lazy="dynamic", cascade="all, delete-orphan"),
    )
    config = db.relationship("NotificationConfig")

    def __repr__(self) -> str:
        return (
            f"<NotificationLog id={self.id} exec={self.execution_id} "
            f"channel={self.channel.value} status={self.status.value}>"
        )
