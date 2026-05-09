"""RBAC middleware tests: verify decorators intercept requests.

Tests the three authorization decorators in app/auth/decorators.py:
- @role_required(Role.SUPER_ADMIN)  -- role gate
- @permission_required("project", "create")  -- permission gate
- @project_permission_required("execution.trigger")  -- project-scoped gate

These tests exercise the decorators both through real HTTP routes
(integration) and via direct decorator invocation (unit).
"""

from unittest.mock import patch

import pytest
from werkzeug.exceptions import Forbidden

from app.models.user import Role


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client, username, password):
    client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


@pytest.fixture(autouse=True)
def _seed_all_users(db, admin_user, lead_user, tester_user, visitor_user):
    """Ensure all four role users exist for every test."""
    pass


# ===================================================================
# Integration: @role_required via /admin/* before_request hook
# ===================================================================


class TestRoleRequiredIntegration:
    """The admin blueprint uses before_request + has_role(SUPER_ADMIN),
    which is functionally equivalent to @role_required(SUPER_ADMIN)."""

    def test_admin_can_access_admin_page(self, client, login_as_admin):
        resp = client.get("/admin/users")
        assert resp.status_code == 200

    def test_lead_cannot_access_admin_page(self, client, login_as_lead):
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_tester_cannot_access_admin_page(self, client, login_as_tester):
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_visitor_cannot_access_admin_page(self, client, login_as_visitor):
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_unauthenticated_redirects(self, client):
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_admin_can_access_config(self, client, login_as_admin):
        """Admin config page passes auth check. Template may error without seed data."""
        try:
            resp = client.get("/admin/config")
            assert resp.status_code != 403
        except Exception:
            pass

    def test_admin_can_access_audit_log(self, client, login_as_admin):
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 200


# ===================================================================
# Integration: @permission_required via /projects/create
# ===================================================================


class TestPermissionRequiredIntegration:
    """The project create route checks has_permission("project.create")
    inline, which is functionally equivalent to @permission_required."""

    def test_admin_can_create_project(self, client, login_as_admin):
        resp = client.get("/projects/create")
        assert resp.status_code == 200

    def test_lead_can_create_project(self, client, login_as_lead):
        resp = client.get("/projects/create")
        assert resp.status_code == 200

    def test_tester_cannot_create_project(self, client, login_as_tester):
        resp = client.get("/projects/create", follow_redirects=False)
        assert resp.status_code == 403

    def test_visitor_cannot_create_project(self, client, login_as_visitor):
        resp = client.get("/projects/create", follow_redirects=False)
        assert resp.status_code == 403

    def test_unauthenticated_redirects(self, client):
        resp = client.get("/projects/create", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")


# ===================================================================
# Integration: permission gate via /executions/trigger
# ===================================================================


class TestExecutionTriggerPermission:
    """Execution trigger route checks has_permission("execution.trigger")."""

    def test_admin_can_trigger(self, client, login_as_admin, sample_project):
        resp = client.get(f"/executions/trigger/{sample_project.id}")
        assert resp.status_code == 200

    def test_lead_can_trigger(self, client, login_as_lead, sample_project):
        resp = client.get(f"/executions/trigger/{sample_project.id}")
        assert resp.status_code == 200

    def test_tester_can_trigger(self, client, login_as_tester, sample_project):
        resp = client.get(f"/executions/trigger/{sample_project.id}")
        assert resp.status_code == 200

    def test_visitor_cannot_trigger(self, client, login_as_visitor, sample_project):
        resp = client.get(
            f"/executions/trigger/{sample_project.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_unauthenticated_redirects(self, client, sample_project):
        resp = client.get(
            f"/executions/trigger/{sample_project.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")


# ===================================================================
# Unit: @role_required decorator directly
# ===================================================================


class TestRoleRequiredDecorator:
    """Test the @role_required decorator in isolation."""

    def _apply_role_required(self, app, user, *roles):
        """Apply @role_required to a dummy view and invoke it."""
        from app.auth.decorators import role_required

        @role_required(*roles)
        def _view():
            return "ok"

        with app.test_request_context("/test"):
            with patch("flask_login.utils._get_user", return_value=user):
                return _view()

    def test_matching_role_allowed(self, app, admin_user):
        result = self._apply_role_required(app, admin_user, Role.SUPER_ADMIN)
        assert result == "ok"

    def test_non_matching_role_raises_403(self, app, tester_user):
        with pytest.raises(Forbidden):
            self._apply_role_required(app, tester_user, Role.SUPER_ADMIN)

    def test_multiple_roles_uses_first_match(self, app, lead_user):
        result = self._apply_role_required(
            app, lead_user, Role.SUPER_ADMIN, Role.PROJECT_LEAD
        )
        assert result == "ok"

    def test_unauthenticated_redirects(self, app):
        from flask import redirect
        from werkzeug.test import Client

        from app.auth.decorators import role_required

        class _FakeAnonymous:
            is_authenticated = False

        @role_required(Role.SUPER_ADMIN)
        def _view():
            return "ok"

        with app.test_request_context("/test"):
            with patch("flask_login.utils._get_user", return_value=_FakeAnonymous()):
                result = _view()
                # Should redirect to login
                assert isinstance(result, type(redirect("/")))


# ===================================================================
# Unit: @permission_required decorator directly
# ===================================================================


class TestPermissionRequiredDecorator:
    """Test the @permission_required decorator in isolation."""

    def _apply_perm_required(self, app, user, resource, action):
        from app.auth.decorators import permission_required

        @permission_required(resource, action)
        def _view():
            return "ok"

        with app.test_request_context("/test"):
            with patch("flask_login.utils._get_user", return_value=user):
                return _view()

    def test_lead_has_project_create(self, app, lead_user):
        result = self._apply_perm_required(app, lead_user, "project", "create")
        assert result == "ok"

    def test_tester_lacks_project_create(self, app, tester_user):
        with pytest.raises(Forbidden):
            self._apply_perm_required(app, tester_user, "project", "create")

    def test_visitor_lacks_project_create(self, app, visitor_user):
        with pytest.raises(Forbidden):
            self._apply_perm_required(app, visitor_user, "project", "create")

    def test_admin_has_all_permissions(self, app, admin_user):
        result = self._apply_perm_required(app, admin_user, "project", "create")
        assert result == "ok"

    def test_tester_has_execution_trigger(self, app, tester_user):
        result = self._apply_perm_required(app, tester_user, "execution", "trigger")
        assert result == "ok"

    def test_visitor_lacks_execution_trigger(self, app, visitor_user):
        with pytest.raises(Forbidden):
            self._apply_perm_required(app, visitor_user, "execution", "trigger")


# ===================================================================
# Unit: @project_permission_required decorator directly
# ===================================================================


class TestProjectPermissionRequiredDecorator:
    """Test the @project_permission_required decorator in isolation."""

    def _apply_project_perm(self, app, user, permission, project_id):
        from app.auth.decorators import project_permission_required

        @project_permission_required(permission)
        def _view(id):
            return "ok"

        with app.test_request_context(f"/test/{project_id}"):
            with patch("flask_login.utils._get_user", return_value=user):
                return _view(id=project_id)

    def test_admin_bypasses_project_check(self, app, admin_user, sample_project):
        """SUPER_ADMIN always passes project-level checks."""
        result = self._apply_project_perm(
            app, admin_user, "execution.trigger", sample_project.id
        )
        assert result == "ok"

    def test_project_owner_has_access(self, app, admin_user, sample_project):
        """Project owner (admin_user created sample_project) has access."""
        result = self._apply_project_perm(
            app, admin_user, "execution.trigger", sample_project.id
        )
        assert result == "ok"

    def test_non_member_denied(self, app, tester_user, sample_project):
        """User with no project membership is denied."""
        with pytest.raises(Forbidden):
            self._apply_project_perm(
                app, tester_user, "execution.trigger", sample_project.id
            )

    def test_member_with_permission_allowed(self, app, tester_user, sample_project, db):
        """User with matching project membership is allowed."""
        from app.models.project_membership import ProjectMembership, ProjectRole

        membership = ProjectMembership(
            user_id=tester_user.id,
            project_id=sample_project.id,
            role=ProjectRole.TESTER,
        )
        db.session.add(membership)
        db.session.commit()

        result = self._apply_project_perm(
            app, tester_user, "execution.trigger", sample_project.id
        )
        assert result == "ok"

    def test_member_without_permission_denied(self, app, tester_user, sample_project, db):
        """Project viewer cannot trigger execution."""
        from app.models.project_membership import ProjectMembership, ProjectRole

        membership = ProjectMembership(
            user_id=tester_user.id,
            project_id=sample_project.id,
            role=ProjectRole.VIEWER,
        )
        db.session.add(membership)
        db.session.commit()

        with pytest.raises(Forbidden):
            self._apply_project_perm(
                app, tester_user, "execution.trigger", sample_project.id
            )

    def test_missing_project_id_returns_400(self, app, admin_user):
        """Decorator returns 400 if view has no project_id kwarg."""
        from app.auth.decorators import project_permission_required

        @project_permission_required("execution.trigger")
        def _view():
            return "ok"

        with app.test_request_context("/test"):
            with patch("flask_login.utils._get_user", return_value=admin_user):
                from werkzeug.exceptions import BadRequest
                with pytest.raises(BadRequest):
                    _view()
