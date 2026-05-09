"""Admin routes: user CRUD, system config, and audit log viewer (super_admin only)."""

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.admin import admin_bp
from app.admin.forms import SystemConfigForm, UserAdminForm
from app.admin.services import validate_all_configs
from app.auth.decorators import role_required
from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.system_config import SystemConfig
from app.models.user import Role, User
from app.utils.audit import log_audit


@admin_bp.before_request
@login_required
def require_super_admin():
    """All admin endpoints require super_admin role."""
    if not current_user.has_role(Role.SUPER_ADMIN):
        abort(403)


# ------------------------------------------------------------------
# List
# ------------------------------------------------------------------

@admin_bp.route("/users")
def list_users():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("q", "").strip()

    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )

    pagination = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        "admin/users.html",
        pagination=pagination,
        users=pagination.items,
        search=search,
    )


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------

@admin_bp.route("/users/create", methods=["GET", "POST"])
def create_user():
    form = UserAdminForm()
    if form.validate_on_submit():
        existing = User.query.filter(
            db.or_(User.username == form.username.data, User.email == form.email.data)
        ).first()
        if existing:
            flash("A user with that username or email already exists.", "danger")
            return render_template("admin/user_form.html", form=form, editing=False)

        user = User(
            username=form.username.data,
            email=form.email.data,
            role=Role(form.role.data),
            is_active=form.is_active.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        log_audit(
            "admin.user.create",
            resource_type="user",
            resource_id=user.id,
            new_value={"username": user.username, "role": user.role.value},
        )
        flash(f"User {user.username} created.", "success")
        return redirect(url_for("admin.list_users"))

    return render_template("admin/user_form.html", form=form, editing=False)


# ------------------------------------------------------------------
# Edit
# ------------------------------------------------------------------

@admin_bp.route("/users/<int:id>/edit", methods=["GET", "POST"])
def edit_user(id: int):
    user = User.query.get_or_404(id)

    form = UserAdminForm(obj=user)
    # Pre-populate the role select
    if request.method == "GET":
        form.role.data = user.role.value

    if form.validate_on_submit():
        # Check uniqueness conflicts
        conflict = User.query.filter(
            db.and_(
                db.or_(User.username == form.username.data, User.email == form.email.data),
                User.id != user.id,
            )
        ).first()
        if conflict:
            flash("Another user with that username or email already exists.", "danger")
            return render_template("admin/user_form.html", form=form, editing=True, user=user)

        old_values = {
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
        }

        user.username = form.username.data
        user.email = form.email.data
        user.role = Role(form.role.data)
        user.is_active = form.is_active.data

        if form.password.data:
            user.set_password(form.password.data)

        db.session.commit()

        new_values = {
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
        }
        log_audit(
            "admin.user.edit",
            resource_type="user",
            resource_id=user.id,
            old_value=old_values,
            new_value=new_values,
        )
        flash(f"User {user.username} updated.", "success")
        return redirect(url_for("admin.list_users"))

    return render_template("admin/user_form.html", form=form, editing=True, user=user)


# ------------------------------------------------------------------
# Delete (soft-delete: deactivate)
# ------------------------------------------------------------------

@admin_bp.route("/users/<int:id>/delete", methods=["POST"])
def delete_user(id: int):
    user = User.query.get_or_404(id)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin.list_users"))

    old_values = {"username": user.username, "is_active": user.is_active}
    user.is_active = False
    db.session.commit()

    log_audit(
        "admin.user.deactivate",
        resource_type="user",
        resource_id=user.id,
        old_value=old_values,
        new_value={"is_active": False},
    )
    flash(f"User {user.username} has been deactivated.", "success")
    return redirect(url_for("admin.list_users"))


# ------------------------------------------------------------------
# System Config
# ------------------------------------------------------------------


@admin_bp.route("/config", methods=["GET"])
def config_page():
    """Render the system configuration management page."""
    configs = SystemConfig.query.order_by(SystemConfig.key).all()
    form = SystemConfigForm()
    return render_template("admin/config.html", configs=configs, form=form)


@admin_bp.route("/config", methods=["POST"])
def update_config():
    """Update one or more system configuration values."""
    form = SystemConfigForm()
    if not form.validate_on_submit():
        flash("Invalid form submission. Please try again.", "danger")
        return redirect(url_for("admin.config_page"))

    # Collect submitted config values (all form fields prefixed with "config_")
    submitted: dict[str, str] = {}
    for key in request.form:
        if key.startswith("config_"):
            cfg_key = key[len("config_"):]
            submitted[cfg_key] = request.form[key]

    if not submitted:
        flash("No configuration changes submitted.", "warning")
        return redirect(url_for("admin.config_page"))

    # Validate
    all_valid, errors = validate_all_configs(submitted)
    if not all_valid:
        for k, msg in errors.items():
            flash(msg, "danger")
        configs = SystemConfig.query.order_by(SystemConfig.key).all()
        return render_template("admin/config.html", configs=configs, form=form)

    # Apply changes and collect audit info
    changes = []
    for cfg_key, raw_value in submitted.items():
        cfg = SystemConfig.query.filter_by(key=cfg_key).first()
        if cfg is None:
            continue
        old_value = cfg.display_value()
        SystemConfig.set(cfg_key, raw_value, user_id=current_user.id)
        new_value = cfg.display_value()  # refreshed after set
        if old_value != new_value:
            changes.append({"key": cfg_key, "old": old_value, "new": new_value})

    if changes:
        log_audit(
            "admin.config.update",
            resource_type="system_config",
            new_value={"changes": changes},
        )
        flash(f"Updated {len(changes)} configuration value(s).", "success")
    else:
        flash("No values were changed.", "info")

    return redirect(url_for("admin.config_page"))


# ------------------------------------------------------------------
# Audit Log Viewer
# ------------------------------------------------------------------


@admin_bp.route("/audit-log")
def audit_log_viewer():
    """Paginated audit log viewer with filters."""
    page = request.args.get("page", 1, type=int)
    per_page = 50

    # Filter parameters
    filter_user = request.args.get("user", "").strip()
    filter_action = request.args.get("action", "").strip()
    filter_resource = request.args.get("resource_type", "").strip()
    filter_date_from = request.args.get("date_from", "").strip()
    filter_date_to = request.args.get("date_to", "").strip()

    query = AuditLog.query

    if filter_user:
        query = query.filter(AuditLog.username.ilike(f"%{filter_user}%"))
    if filter_action:
        query = query.filter(AuditLog.action.ilike(f"%{filter_action}%"))
    if filter_resource:
        query = query.filter(AuditLog.resource_type == filter_resource)
    if filter_date_from:
        try:
            from datetime import datetime

            dt = datetime.strptime(filter_date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if filter_date_to:
        try:
            from datetime import datetime, timedelta

            dt = datetime.strptime(filter_date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < dt)
        except ValueError:
            pass

    # Distinct values for filter dropdowns
    all_users = (
        db.session.query(AuditLog.username)
        .distinct()
        .order_by(AuditLog.username)
        .all()
    )
    all_actions = (
        db.session.query(AuditLog.action)
        .distinct()
        .order_by(AuditLog.action)
        .all()
    )
    all_resource_types = (
        db.session.query(AuditLog.resource_type)
        .filter(AuditLog.resource_type.isnot(None))
        .distinct()
        .order_by(AuditLog.resource_type)
        .all()
    )

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        "admin/audit_log.html",
        pagination=pagination,
        logs=pagination.items,
        filter_user=filter_user,
        filter_action=filter_action,
        filter_resource=filter_resource,
        filter_date_from=filter_date_from,
        filter_date_to=filter_date_to,
        all_users=[u[0] for u in all_users],
        all_actions=[a[0] for a in all_actions],
        all_resource_types=[r[0] for r in all_resource_types],
    )
