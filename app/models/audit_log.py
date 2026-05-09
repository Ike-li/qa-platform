"""Audit log model for tracking user actions."""

from datetime import datetime, timezone

from app.extensions import db


class AuditLog(db.Model):
    """Immutable record of a user action within the platform."""

    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Who performed the action
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    username = db.Column(db.String(80), nullable=False, default="system")

    # What happened
    action = db.Column(db.String(100), nullable=False, index=True)
    resource_type = db.Column(db.String(50), nullable=True, index=True)
    resource_id = db.Column(db.String(64), nullable=True)

    # Change details (stored as JSON strings)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)

    # Request context
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(256), nullable=True)

    # Timestamp
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationship
    user = db.relationship("User", backref=db.backref("audit_logs", lazy="dynamic"))

    def __repr__(self) -> str:
        return (
            f"<AuditLog action={self.action!r} "
            f"user={self.username!r} "
            f"resource={self.resource_type}:{self.resource_id}>"
        )
