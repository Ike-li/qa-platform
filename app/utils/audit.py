"""Audit logging utility."""

from flask import request
from flask_login import current_user

from app.extensions import db
from app.models.audit_log import AuditLog


def log_audit(
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    old_value=None,
    new_value=None,
    username: str | None = None,
    user_id: int | None = None,
) -> AuditLog:
    """Create and persist an audit log entry.

    Parameters
    ----------
    action:
        Dot-separated action identifier, e.g. ``"user.login"``.
    resource_type:
        The entity type affected, e.g. ``"user"``.
    resource_id:
        The primary key (as string) of the affected entity.
    old_value:
        Serializable snapshot of the state *before* the change.
    new_value:
        Serializable snapshot of the state *after* the change.
    username:
        Override the recorded username (defaults to current_user).
    user_id:
        Override the recorded user id (defaults to current_user).
    """
    try:
        ip_addr = request.remote_addr if request else None
        ua = request.headers.get("User-Agent", "")[:256] if request else None
    except RuntimeError:
        ip_addr = None
        ua = None

    # Resolve user info from current_user when not explicitly provided
    if user_id is None:
        try:
            if current_user and current_user.is_authenticated:
                user_id = current_user.id
        except Exception:
            pass

    if username is None:
        try:
            if current_user and current_user.is_authenticated:
                username = current_user.username
        except Exception:
            username = "system"

    entry = AuditLog(
        user_id=user_id,
        username=username or "system",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_addr,
        user_agent=ua,
    )
    db.session.add(entry)
    db.session.commit()
    return entry
