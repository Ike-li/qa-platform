"""Authorization decorators for role- and permission-based access control."""

import functools

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.models.user import Role


def role_required(*roles: Role):
    """Restrict a view to users whose role is in *roles*.

    Unauthenticated users are redirected to the login page.
    Authenticated users without the required role receive a 403.

    Usage::

        @role_required(Role.SUPER_ADMIN)
        def admin_only():
            ...
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login", next=request.url))
            if not current_user.has_role(*roles):
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def permission_required(resource: str, action: str):
    """Restrict a view to users who hold the ``resource.action`` permission.

    The permission string is constructed as ``f"{resource}.{action}"``
    and looked up against the user's role permission set.

    Usage::

        @permission_required("project", "create")
        def create_project():
            ...
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login", next=request.url))
            perm = f"{resource}.{action}"
            if not current_user.has_permission(perm):
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator
