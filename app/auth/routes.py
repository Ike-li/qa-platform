"""Authentication routes: login, logout, profile."""

import logging
import os
from urllib.parse import urlparse

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import auth_bp
from app.auth.forms import LoginForm, ProfileForm
from app.extensions import db
from app.models.user import User
from app.utils.audit import log_audit

logger = logging.getLogger(__name__)

# Login rate limiting constants
LOGIN_RATE_LIMIT = 5  # max attempts
LOGIN_RATE_WINDOW = 60  # seconds


def _check_login_rate_limit(ip: str) -> bool:
    """Return True if the IP is allowed to attempt login. Uses Redis counter."""
    try:
        import redis as redis_lib
        r = redis_lib.from_url(
            os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
        )
        key = f"login_rate:{ip}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, LOGIN_RATE_WINDOW)
        return count <= LOGIN_RATE_LIMIT
    except Exception:
        logger.debug("Rate limit check failed, allowing login")
        return True


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.profile"))

    # Rate limiting
    client_ip = request.remote_addr or "unknown"
    if not _check_login_rate_limit(client_ip):
        flash("登录尝试次数过多，请稍后再试。", "danger")
        return render_template("auth/login.html", form=LoginForm()), 429

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("用户名或密码错误。", "danger")
            log_audit("user.login.failed", resource_type="user", new_value={"username": form.username.data})
            return render_template("auth/login.html", form=form), 401

        if not user.is_active:
            flash("您的账号已被停用，请联系管理员。", "warning")
            log_audit("user.login.inactive", resource_type="user", resource_id=user.id)
            return render_template("auth/login.html", form=form), 403

        login_user(user, remember=form.remember_me.data)
        log_audit("user.login", resource_type="user", resource_id=user.id)

        # Reset rate limit on successful login
        try:
            import redis as redis_lib
            r = redis_lib.from_url(
                __import__("os").environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
            )
            r.delete(f"login_rate:{client_ip}")
        except Exception:
            pass

        next_page = request.args.get("next")
        if not _is_safe_url(next_page):
            next_page = None
        return redirect(next_page or url_for("auth.profile"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_audit("user.logout", resource_type="user", resource_id=current_user.id)
    logout_user()
    flash("已成功退出登录。", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)

    if form.validate_on_submit():
        # Handle password change if requested
        if form.new_password.data:
            if not form.current_password.data:
                flash("设置新密码时需要输入当前密码。", "danger")
                return render_template("auth/profile.html", form=form)

            if not current_user.check_password(form.current_password.data):
                flash("当前密码不正确。", "danger")
                return render_template("auth/profile.html", form=form)

            current_user.set_password(form.new_password.data)
            flash("密码更新成功。", "success")
            log_audit(
                "user.password_change",
                resource_type="user",
                resource_id=current_user.id,
            )

        # Update email
        old_email = current_user.email
        if form.email.data != old_email:
            current_user.email = form.email.data
            log_audit(
                "user.email_change",
                resource_type="user",
                resource_id=current_user.id,
                old_value={"email": old_email},
                new_value={"email": form.email.data},
            )

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        flash("个人资料已更新。", "success")
        return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html", form=form)


def _is_safe_url(target: str | None) -> bool:
    """Validate that *target* is a safe redirect (same host, no scheme override)."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target)
    return test.scheme in ("http", "https") and (
        not test.netloc or test.netloc == ref.netloc
    )
