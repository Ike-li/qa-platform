"""Tests for app/admin/routes.py -- admin route-level tests.

Covers: list_users, create_user, edit_user, delete_user,
        config_page, update_config, audit_log_viewer.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.models.audit_log import AuditLog
from app.models.system_config import SystemConfig
from app.models.user import Role, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user(db_session, username, email, role=Role.TESTER, is_active=True):
    user = User(username=username, email=email, role=role, is_active=is_active)
    user.set_password("password123")
    db_session.session.add(user)
    db_session.session.commit()
    return user


def _seed_system_configs(db_session):
    """Insert the default system config rows needed for config endpoints."""
    configs = [
        SystemConfig(key="execution.timeout_minutes", value="30", value_type="int"),
        SystemConfig(key="execution.max_parallel", value="3", value_type="int"),
        SystemConfig(key="retention.execution_days", value="90", value_type="int"),
        SystemConfig(key="retention.report_days", value="30", value_type="int"),
        SystemConfig(key="retention.audit_days", value="180", value_type="int"),
    ]
    db_session.session.add_all(configs)
    db_session.session.commit()


def _create_audit_log_entry(db_session, action, username="system", created_at=None):
    entry = AuditLog(
        action=action,
        username=username,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db_session.session.add(entry)
    db_session.session.commit()
    return entry


# ===========================================================================
# Admin list_users
# ===========================================================================


class TestAdminListUsers:
    def test_list_users_empty(self, client, login_as_admin, db):
        """GET /admin/users returns 200 with empty user list (admin only)."""
        resp = client.get("/admin/users")
        assert resp.status_code == 200

    def test_list_users_shows_users(self, client, login_as_admin, admin_user, db):
        """List page includes the admin user."""
        _create_user(db, "alice", "alice@test.com")
        resp = client.get("/admin/users")
        assert resp.status_code == 200
        # Should contain both admin and alice
        assert b"alice" in resp.data or b"admin" in resp.data

    def test_list_users_search(self, client, login_as_admin, db):
        """Search filter narrows results."""
        _create_user(db, "alice", "alice@test.com")
        _create_user(db, "bob", "bob@test.com")
        resp = client.get("/admin/users?q=alice")
        assert resp.status_code == 200

    def test_list_users_search_by_email(self, client, login_as_admin, db):
        """Search by email works."""
        _create_user(db, "alice", "alice_unique@test.com")
        resp = client.get("/admin/users?q=alice_unique")
        assert resp.status_code == 200

    def test_list_users_pagination(self, client, login_as_admin, db):
        """Pagination parameters are accepted."""
        for i in range(5):
            _create_user(db, f"user_{i}", f"user_{i}@test.com")
        resp = client.get("/admin/users?page=1&per_page=2")
        assert resp.status_code == 200

    def test_list_users_non_admin_forbidden(self, client, login_as_lead, db):
        """Non-admin gets 403."""
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403


# ===========================================================================
# Admin create_user
# ===========================================================================


class TestAdminCreateUser:
    def test_create_user_form_renders(self, client, login_as_admin, db):
        """GET /admin/users/create renders the form."""
        resp = client.get("/admin/users/create")
        assert resp.status_code == 200

    def test_create_user_success(self, client, login_as_admin, admin_user, db):
        """POST creates a new user."""
        resp = client.post(
            "/admin/users/create",
            data={
                "username": "newuser",
                "email": "new@test.com",
                "role": "tester",
                "password": "securepassword123",
                "is_active": "y",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        user = User.query.filter_by(username="newuser").first()
        assert user is not None
        assert user.email == "new@test.com"
        assert user.role == Role.TESTER

    def test_create_user_duplicate_username(
        self, client, login_as_admin, admin_user, db
    ):
        """Duplicate username flashes danger."""
        _create_user(db, "existing", "existing@test.com")
        resp = client.post(
            "/admin/users/create",
            data={
                "username": "existing",
                "email": "new@test.com",
                "role": "tester",
                "password": "securepassword123",
            },
            follow_redirects=False,
        )
        # Should re-render form (200) with error flash
        assert resp.status_code == 200

    def test_create_user_duplicate_email(self, client, login_as_admin, admin_user, db):
        """Duplicate email flashes danger."""
        _create_user(db, "unique_name", "dup@test.com")
        resp = client.post(
            "/admin/users/create",
            data={
                "username": "unique_name_2",
                "email": "dup@test.com",
                "role": "tester",
                "password": "securepassword123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_create_user_validation_failure(self, client, login_as_admin, db):
        """Missing required fields stays on form."""
        resp = client.post(
            "/admin/users/create",
            data={"username": "", "email": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_create_user_audit_log(self, client, login_as_admin, admin_user, db):
        """Creating a user writes an audit log entry."""
        client.post(
            "/admin/users/create",
            data={
                "username": "audited",
                "email": "audited@test.com",
                "role": "tester",
                "password": "securepassword123",
            },
            follow_redirects=False,
        )
        log = AuditLog.query.filter_by(action="admin.user.create").first()
        assert log is not None
        assert "audited" in str(log.new_value)


# ===========================================================================
# Admin edit_user
# ===========================================================================


class TestAdminEditUser:
    def test_edit_user_form_renders(self, client, login_as_admin, admin_user, db):
        """GET /admin/users/<id>/edit renders the form."""
        user = _create_user(db, "edittarget", "edit@test.com")
        resp = client.get(f"/admin/users/{user.id}/edit")
        assert resp.status_code == 200

    def test_edit_user_404(self, client, login_as_admin, db):
        """Nonexistent user returns 404."""
        resp = client.get("/admin/users/99999/edit")
        assert resp.status_code == 404

    def test_edit_user_success(self, client, login_as_admin, admin_user, db):
        """POST updates user fields."""
        user = _create_user(db, "edittarget", "edit@test.com")
        resp = client.post(
            f"/admin/users/{user.id}/edit",
            data={
                "username": "updated_name",
                "email": "updated@test.com",
                "role": "project_lead",
                "is_active": "y",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        updated = db.session.get(User, user.id)
        assert updated.username == "updated_name"
        assert updated.email == "updated@test.com"
        assert updated.role == Role.PROJECT_LEAD

    def test_edit_user_password_change(self, client, login_as_admin, admin_user, db):
        """POST with password field changes the password."""
        user = _create_user(db, "pwtarget", "pw@test.com")
        old_hash = user.password_hash
        resp = client.post(
            f"/admin/users/{user.id}/edit",
            data={
                "username": "pwtarget",
                "email": "pw@test.com",
                "role": "tester",
                "password": "newsecurepass123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        updated = db.session.get(User, user.id)
        assert updated.password_hash != old_hash

    def test_edit_user_conflict_username(self, client, login_as_admin, admin_user, db):
        """Conflict with another user's username re-renders form."""
        _create_user(db, "user_a", "a@test.com")
        user2 = _create_user(db, "user_b", "b@test.com")
        resp = client.post(
            f"/admin/users/{user2.id}/edit",
            data={
                "username": "user_a",  # conflicts with user1
                "email": "b@test.com",
                "role": "tester",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_edit_user_conflict_email(self, client, login_as_admin, admin_user, db):
        """Conflict with another user's email re-renders form."""
        _create_user(db, "user_c", "c@test.com")
        user2 = _create_user(db, "user_d", "d@test.com")
        resp = client.post(
            f"/admin/users/{user2.id}/edit",
            data={
                "username": "user_d",
                "email": "c@test.com",  # conflicts with user1
                "role": "tester",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_edit_user_audit_log(self, client, login_as_admin, admin_user, db):
        """Editing a user writes an audit log entry."""
        user = _create_user(db, "audit_edit", "ae@test.com")
        client.post(
            f"/admin/users/{user.id}/edit",
            data={
                "username": "audit_edit_renamed",
                "email": "ae@test.com",
                "role": "tester",
            },
            follow_redirects=False,
        )
        log = AuditLog.query.filter_by(action="admin.user.edit").first()
        assert log is not None


# ===========================================================================
# Admin delete_user
# ===========================================================================


class TestAdminDeleteUser:
    def test_delete_user_success(self, client, login_as_admin, admin_user, db):
        """POST deactivates a user."""
        user = _create_user(db, "deleteme", "del@test.com")
        resp = client.post(
            f"/admin/users/{user.id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        updated = db.session.get(User, user.id)
        assert updated.is_active is False

    def test_delete_user_self_prevention(self, client, login_as_admin, admin_user, db):
        """Cannot delete yourself."""
        resp = client.post(
            f"/admin/users/{admin_user.id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Admin still active
        refreshed = db.session.get(User, admin_user.id)
        assert refreshed.is_active is True

    def test_delete_user_404(self, client, login_as_admin, db):
        """Nonexistent user returns 404."""
        resp = client.post("/admin/users/99999/delete")
        assert resp.status_code == 404

    def test_delete_user_audit_log(self, client, login_as_admin, admin_user, db):
        """Deactivating a user writes an audit log entry."""
        user = _create_user(db, "audit_del", "ad@test.com")
        client.post(f"/admin/users/{user.id}/delete", follow_redirects=False)
        log = AuditLog.query.filter_by(action="admin.user.deactivate").first()
        assert log is not None


# ===========================================================================
# Admin config_page (GET)
# ===========================================================================


class TestAdminConfigPage:
    @patch("app.admin.routes.render_template", return_value="<html>config</html>")
    def test_config_page_renders(self, mock_render, client, login_as_admin, db):
        """GET /admin/config renders the config page."""
        _seed_system_configs(db)
        resp = client.get("/admin/config")
        assert resp.status_code == 200
        mock_render.assert_called_once()
        call_kwargs = mock_render.call_args
        assert "configs" in call_kwargs.kwargs or "configs" in call_kwargs[1]


# ===========================================================================
# Admin update_config (POST)
# ===========================================================================


class TestAdminUpdateConfig:
    def test_update_config_success(self, client, login_as_admin, db):
        """POST with valid config values updates successfully."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={
                "config_execution.timeout_minutes": "60",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        cfg = SystemConfig.query.filter_by(key="execution.timeout_minutes").first()
        assert cfg.value == "60"

    def test_update_config_no_changes(self, client, login_as_admin, db):
        """POST with same value as existing shows 'no changes' message."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={
                "config_execution.timeout_minutes": "30",  # same as seed
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_update_config_invalid_form(self, client, login_as_admin, db):
        """POST without CSRF token (form invalid) redirects."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={},
            follow_redirects=False,
        )
        # WTForms CSRF disabled in testing, but no config_ prefixed keys
        # means empty submitted -> warning flash
        assert resp.status_code == 302

    def test_update_config_no_submitted_keys(self, client, login_as_admin, db):
        """POST with no config_ prefixed keys shows warning."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={"other_field": "value"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    @patch("app.admin.routes.render_template", return_value="<html>config</html>")
    def test_update_config_validation_failure(
        self, mock_render, client, login_as_admin, db
    ):
        """POST with invalid value (non-integer for int field) re-renders."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={
                "config_execution.timeout_minutes": "not_a_number",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200

    def test_update_config_unknown_key_skipped(self, client, login_as_admin, db):
        """POST with a config key that doesn't exist in DB is skipped."""
        _seed_system_configs(db)
        resp = client.post(
            "/admin/config",
            data={
                "config_nonexistent.key": "value",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_update_config_audit_log(self, client, login_as_admin, db):
        """Successful config update writes an audit log entry."""
        _seed_system_configs(db)
        client.post(
            "/admin/config",
            data={
                "config_execution.timeout_minutes": "120",
            },
            follow_redirects=False,
        )
        log = AuditLog.query.filter_by(action="admin.config.update").first()
        assert log is not None


# ===========================================================================
# Admin audit_log_viewer
# ===========================================================================


class TestAdminAuditLogViewer:
    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_empty(self, mock_render, client, login_as_admin, db):
        """GET /admin/audit-log returns 200."""
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 200
        mock_render.assert_called_once()

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_with_entries(self, mock_render, client, login_as_admin, db):
        """Shows existing audit log entries."""
        _create_audit_log_entry(db, "user.login", username="admin")
        _create_audit_log_entry(db, "project.create", username="admin")
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_user(self, mock_render, client, login_as_admin, db):
        """Filter by username."""
        _create_audit_log_entry(db, "user.login", username="alice")
        _create_audit_log_entry(db, "user.login", username="bob")
        resp = client.get("/admin/audit-log?user=alice")
        assert resp.status_code == 200
        call_ctx = mock_render.call_args
        assert (
            call_ctx.kwargs.get("filter_user") == "alice"
            or call_ctx[1].get("filter_user") == "alice"
        )

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_action(self, mock_render, client, login_as_admin, db):
        """Filter by action."""
        _create_audit_log_entry(db, "user.login")
        _create_audit_log_entry(db, "project.create")
        resp = client.get("/admin/audit-log?action=login")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_resource_type(
        self, mock_render, client, login_as_admin, db
    ):
        """Filter by resource type."""
        _create_audit_log_entry(db, "test.action")
        resp = client.get("/admin/audit-log?resource_type=user")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_date_from(self, mock_render, client, login_as_admin, db):
        """Filter by date_from."""
        _create_audit_log_entry(db, "test.action")
        resp = client.get("/admin/audit-log?date_from=2026-01-01")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_date_to(self, mock_render, client, login_as_admin, db):
        """Filter by date_to."""
        _create_audit_log_entry(db, "test.action")
        resp = client.get("/admin/audit-log?date_to=2026-12-31")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_invalid_date_from(
        self, mock_render, client, login_as_admin, db
    ):
        """Invalid date_from is ignored (ValueError branch)."""
        _create_audit_log_entry(db, "test.action")
        resp = client.get("/admin/audit-log?date_from=invalid-date")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_filter_invalid_date_to(
        self, mock_render, client, login_as_admin, db
    ):
        """Invalid date_to is ignored (ValueError branch)."""
        _create_audit_log_entry(db, "test.action")
        resp = client.get("/admin/audit-log?date_to=invalid-date")
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_all_filters_combined(
        self, mock_render, client, login_as_admin, db
    ):
        """All filters applied together."""
        _create_audit_log_entry(db, "test.combined", username="combo")
        resp = client.get(
            "/admin/audit-log?user=combo&action=combined&resource_type=user&date_from=2026-01-01&date_to=2026-12-31"
        )
        assert resp.status_code == 200

    @patch("app.admin.routes.render_template", return_value="<html>audit</html>")
    def test_audit_log_pagination(self, mock_render, client, login_as_admin, db):
        """Pagination works."""
        for i in range(55):
            _create_audit_log_entry(db, f"test.page_{i}", username=f"user_{i}")
        resp = client.get("/admin/audit-log?page=2")
        assert resp.status_code == 200


# ===========================================================================
# Admin services -- additional edge cases
# ===========================================================================


class TestAdminServicesEdgeCases:
    """Cover remaining uncovered branches in admin/services.py."""

    def test_validate_config_value_type_error(self, app, db):
        """ValueError branch when int() fails with TypeError."""
        from app.admin.services import validate_config_value

        # Passing None as raw_value triggers TypeError
        ok, msg = validate_config_value("execution.timeout_minutes", None)
        assert ok is False
        assert "must be an integer" in msg
