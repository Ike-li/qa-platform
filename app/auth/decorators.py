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
                flash("请先登录后再访问此页面。", "warning")
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
                flash("请先登录后再访问此页面。", "warning")
                return redirect(url_for("auth.login", next=request.url))
            perm = f"{resource}.{action}"
            if not current_user.has_permission(perm):
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def project_permission_required(permission: str):
    """Restrict a view to users who hold *permission* within the URL's project.

    Expects the view to receive a ``project_id`` or ``id`` keyword argument.
    SUPER_ADMIN always passes.

    Usage::

        @project_permission_required("execution.trigger")
        def trigger_execution(project_id):
            ...
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("请先登录后再访问此页面。", "warning")
                return redirect(url_for("auth.login", next=request.url))

            project_id = kwargs.get("project_id") or kwargs.get("id")
            if project_id is None:
                abort(400)

            if not current_user.has_project_permission(permission, project_id):
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator
