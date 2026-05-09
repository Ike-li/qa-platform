"""Cross-cutting decorators for the application."""

import functools

from flask import current_app, request


def audit_log(action: str):
    """Decorator that logs an action to the audit trail after the view
    completes successfully (no unhandled exception).

    Usage::

        @audit_log("user.login")
        def login():
            ...

    The log entry is written *after* the wrapped function returns so that
    the database session is not polluted if the view itself rolls back.
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            response = f(*args, **kwargs)

            # Deferred import to avoid circular dependency
            from app.utils.audit import log_audit

            try:
                # Attempt to extract resource info from the URL rule
                resource_type = None
                resource_id = None
                if request.view_args:
                    resource_type = request.view_args.get("resource_type")
                    resource_id = request.view_args.get(
                        "resource_id",
                        request.view_args.get("id"),
                    )

                log_audit(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
            except Exception:
                # Audit failure must never break the user flow
                current_app.logger.exception(
                    "Failed to write audit log for action=%s", action
                )

            return response

        return wrapper

    return decorator
