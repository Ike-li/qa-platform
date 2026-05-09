"""Notification configuration routes and test endpoint."""

import logging

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.notification import NotificationChannel, NotificationConfig
from app.models.project import Project
from app.notifications import notifications_bp
from app.notifications.services import send_dingtalk, send_email, send_wechat

logger = logging.getLogger(__name__)


@notifications_bp.route("/")
@login_required
def list_configs():
    """List all notification configs grouped by project."""
    if not current_user.has_permission("config.manage"):
        abort(403)

    projects = Project.query.order_by(Project.name).all()
    configs_by_project: dict[int, list] = {}
    for p in projects:
        configs_by_project[p.id] = (
            NotificationConfig.query
            .filter_by(project_id=p.id)
            .order_by(NotificationConfig.channel)
            .all()
        )

    return render_template(
        "notifications/configs.html",
        projects=projects,
        configs_by_project=configs_by_project,
        channels=NotificationChannel,
    )


@notifications_bp.route("/create/<int:project_id>", methods=["GET", "POST"])
@login_required
def create_config(project_id: int):
    """Create a notification config for a project."""
    if not current_user.has_permission("config.manage"):
        abort(403)

    project = Project.query.get_or_404(project_id)

    if request.method == "POST":
        channel = request.form.get("channel")
        if not channel:
            flash("Channel is required.", "danger")
            return redirect(url_for("notifications.create_config", project_id=project_id))

        try:
            ch = NotificationChannel(channel)
        except ValueError:
            flash("Invalid channel.", "danger")
            return redirect(url_for("notifications.create_config", project_id=project_id))

        webhook_url = request.form.get("webhook_url", "").strip() or None
        email_recipients = request.form.get("email_recipients", "").strip() or None
        is_active = request.form.get("is_active") == "on"

        # Parse trigger events from checkboxes
        trigger_events = request.form.getlist("trigger_events")

        config = NotificationConfig(
            project_id=project.id,
            channel=ch,
            webhook_url=webhook_url,
            email_recipients=email_recipients,
            is_active=is_active,
            trigger_events=trigger_events,
        )
        db.session.add(config)
        db.session.commit()
        flash(f"Notification channel {ch.value} created for {project.name}.", "success")
        return redirect(url_for("notifications.list_configs"))

    return render_template(
        "notifications/config_form.html",
        project=project,
        channels=NotificationChannel,
        config=None,
    )


@notifications_bp.route("/edit/<int:config_id>", methods=["GET", "POST"])
@login_required
def edit_config(config_id: int):
    """Edit an existing notification config."""
    if not current_user.has_permission("config.manage"):
        abort(403)

    config = NotificationConfig.query.get_or_404(config_id)
    project = config.project

    if request.method == "POST":
        config.webhook_url = request.form.get("webhook_url", "").strip() or None
        config.email_recipients = request.form.get("email_recipients", "").strip() or None
        config.is_active = request.form.get("is_active") == "on"
        config.trigger_events = request.form.getlist("trigger_events")
        db.session.commit()
        flash("Notification config updated.", "success")
        return redirect(url_for("notifications.list_configs"))

    return render_template(
        "notifications/config_form.html",
        project=project,
        channels=NotificationChannel,
        config=config,
    )


@notifications_bp.route("/delete/<int:config_id>", methods=["POST"])
@login_required
def delete_config(config_id: int):
    """Delete a notification config."""
    if not current_user.has_permission("config.manage"):
        abort(403)

    config = NotificationConfig.query.get_or_404(config_id)
    db.session.delete(config)
    db.session.commit()
    flash("Notification config deleted.", "success")
    return redirect(url_for("notifications.list_configs"))


@notifications_bp.route("/test/<int:config_id>", methods=["POST"])
@login_required
def test_notification(config_id: int):
    """Send a test notification through the specified config."""
    if not current_user.has_permission("config.manage"):
        abort(403)

    config = NotificationConfig.query.get_or_404(config_id)
    channel = config.channel

    test_subject = "[QA Platform] Test Notification"
    test_body = (
        f"This is a test notification for project **{config.project.name}** "
        f"via the **{channel.value}** channel.\n\n"
        f"If you received this, the notification channel is configured correctly."
    )

    try:
        if channel == NotificationChannel.EMAIL:
            recipients = [e.strip() for e in (config.email_recipients or "").split(",") if e.strip()]
            if not recipients:
                flash("No email recipients configured.", "warning")
                return redirect(url_for("notifications.list_configs"))
            send_email(recipients, test_subject, test_body)

        elif channel == NotificationChannel.DINGTALK:
            if not config.webhook_url:
                flash("No DingTalk webhook URL configured.", "warning")
                return redirect(url_for("notifications.list_configs"))
            send_dingtalk(config.webhook_url, test_subject, test_body)

        elif channel == NotificationChannel.WECHAT:
            if not config.webhook_url:
                flash("No WeChat webhook URL configured.", "warning")
                return redirect(url_for("notifications.list_configs"))
            send_wechat(config.webhook_url, test_body)

        flash(f"Test notification sent via {channel.value}.", "success")

    except Exception as exc:
        logger.exception("Test notification failed for config %d", config_id)
        flash(f"Failed to send test notification: {exc}", "danger")

    return redirect(url_for("notifications.list_configs"))
