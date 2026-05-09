"""Project-level RBAC tests: verify project-scoped permission checks.

Tests cover:
- Each ProjectRole x permission combination
- SUPER_ADMIN bypass
- Project owner implicit membership
- Unrelated user denial
- Unique constraint on user+project
- project_permission_required decorator
"""

import pytest

from app.models.project import Project
from app.models.project_membership import (
    PROJECT_ROLE_PERMISSIONS,
    ProjectMembership,
    ProjectRole,
)
from app.models.user import Role, User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_owner(db, admin_user):
    """Create a user who owns a project."""
    owner = User(username="projowner", email="owner@test.com", role=Role.TESTER)
    owner.set_password("pass")
    db.session.add(owner)
    db.session.commit()
    return owner


@pytest.fixture
def owned_project(db, project_owner):
    """A project owned by project_owner."""
    project = Project(
        name="Owned Project",
        git_url="https://example.com/repo.git",
        git_branch="main",
        owner_id=project_owner.id,
    )
    db.session.add(project)
    db.session.commit()
    return project


@pytest.fixture
def unrelated_user(db):
    """A user with no project membership."""
    user = User(username="unrelated", email="unrelated@test.com", role=Role.TESTER)
    user.set_password("pass")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def add_membership(db):
    """Factory fixture to add a project membership."""
    def _add(user, project, role=ProjectRole.TESTER):
        membership = ProjectMembership(
            user_id=user.id, project_id=project.id, role=role,
        )
        db.session.add(membership)
        db.session.commit()
        return membership
    return _add


# ---------------------------------------------------------------------------
# Tests: has_project_permission
# ---------------------------------------------------------------------------


class TestHasProjectPermission:
    """Test User.has_project_permission() method."""

    def test_super_admin_bypasses_project_check(self, admin_user, owned_project):
        """SUPER_ADMIN always passes project-level checks."""
        assert admin_user.has_project_permission("execution.trigger", owned_project.id)

    def test_project_owner_implicit_access(self, project_owner, owned_project):
        """Project owner has full access without explicit membership."""
        assert project_owner.has_project_permission("execution.trigger", owned_project.id)
        assert project_owner.has_project_permission("execution.view", owned_project.id)
        assert project_owner.has_project_permission("report.view", owned_project.id)

    def test_unrelated_user_denied(self, unrelated_user, owned_project):
        """User with no membership and not owner is denied."""
        assert not unrelated_user.has_project_permission("execution.trigger", owned_project.id)
        assert not unrelated_user.has_project_permission("execution.view", owned_project.id)

    def test_project_role_tester(self, unrelated_user, owned_project, add_membership):
        """TESTER role can trigger and view, but not manage settings."""
        add_membership(unrelated_user, owned_project, ProjectRole.TESTER)
        assert unrelated_user.has_project_permission("execution.trigger", owned_project.id)
        assert unrelated_user.has_project_permission("execution.view", owned_project.id)
        assert unrelated_user.has_project_permission("report.view", owned_project.id)
        assert not unrelated_user.has_project_permission("project.settings", owned_project.id)
        assert not unrelated_user.has_project_permission("project.members.manage", owned_project.id)

    def test_project_role_viewer(self, unrelated_user, owned_project, add_membership):
        """VIEWER role can only view, not trigger."""
        add_membership(unrelated_user, owned_project, ProjectRole.VIEWER)
        assert unrelated_user.has_project_permission("execution.view", owned_project.id)
        assert unrelated_user.has_project_permission("report.view", owned_project.id)
        assert not unrelated_user.has_project_permission("execution.trigger", owned_project.id)
        assert not unrelated_user.has_project_permission("project.settings", owned_project.id)

    def test_project_role_lead(self, unrelated_user, owned_project, add_membership):
        """LEAD role can manage settings and trigger, but not manage members."""
        add_membership(unrelated_user, owned_project, ProjectRole.LEAD)
        assert unrelated_user.has_project_permission("project.settings", owned_project.id)
        assert unrelated_user.has_project_permission("execution.trigger", owned_project.id)
        assert not unrelated_user.has_project_permission("project.members.manage", owned_project.id)

    def test_project_role_owner_membership(self, unrelated_user, owned_project, add_membership):
        """OWNER membership has all project permissions."""
        add_membership(unrelated_user, owned_project, ProjectRole.OWNER)
        for perm in PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]:
            assert unrelated_user.has_project_permission(perm, owned_project.id)

    def test_project_role_permission_matrix_complete(self):
        """Verify the permission matrix covers all expected permissions."""
        all_perms = set()
        for perms in PROJECT_ROLE_PERMISSIONS.values():
            all_perms.update(perms)
        expected = {"project.settings", "project.members.manage",
                    "execution.trigger", "execution.view", "report.view"}
        assert all_perms == expected


# ---------------------------------------------------------------------------
# Tests: unique constraint
# ---------------------------------------------------------------------------


class TestProjectMembershipConstraints:
    """Test database constraints on ProjectMembership."""

    def test_unique_constraint_user_project(self, db, unrelated_user, owned_project, add_membership):
        """Cannot add two memberships for the same user+project."""
        add_membership(unrelated_user, owned_project, ProjectRole.TESTER)
        with pytest.raises(Exception):  # IntegrityError
            add_membership(unrelated_user, owned_project, ProjectRole.LEAD)
        db.session.rollback()

    def test_different_projects_allowed(self, db, unrelated_user, admin_user, add_membership):
        """Same user can have memberships in different projects."""
        p1 = Project(name="P1", git_url="https://example.com/1.git",
                     git_branch="main", owner_id=admin_user.id)
        p2 = Project(name="P2", git_url="https://example.com/2.git",
                     git_branch="main", owner_id=admin_user.id)
        db.session.add_all([p1, p2])
        db.session.commit()
        add_membership(unrelated_user, p1, ProjectRole.TESTER)
        add_membership(unrelated_user, p2, ProjectRole.LEAD)
        assert unrelated_user.has_project_permission("project.settings", p2.id)
        assert not unrelated_user.has_project_permission("project.settings", p1.id)


# ---------------------------------------------------------------------------
# Tests: decorator
# ---------------------------------------------------------------------------


class TestProjectPermissionDecorator:
    """Test project_permission_required decorator using test_request_context."""

    def test_decorator_denies_without_membership(self, app, unrelated_user, owned_project):
        """Decorator raises 403 for user without project membership."""
        from unittest.mock import patch
        from werkzeug.exceptions import Forbidden
        from app.auth.decorators import project_permission_required

        @project_permission_required("execution.trigger")
        def _view(id):
            return "ok"

        with app.test_request_context(f"/test/{owned_project.id}"):
            with patch("flask_login.utils._get_user", return_value=unrelated_user):
                with pytest.raises(Forbidden):
                    _view(id=owned_project.id)

    def test_decorator_allows_with_membership(self, app, unrelated_user, owned_project, add_membership):
        """Decorator allows user with matching project membership."""
        from unittest.mock import patch
        from app.auth.decorators import project_permission_required

        add_membership(unrelated_user, owned_project, ProjectRole.TESTER)

        @project_permission_required("execution.trigger")
        def _view(id):
            return "ok"

        with app.test_request_context(f"/test/{owned_project.id}"):
            with patch("flask_login.utils._get_user", return_value=unrelated_user):
                result = _view(id=owned_project.id)
                assert result == "ok"

    def test_decorator_allows_super_admin(self, app, admin_user, owned_project):
        """Decorator allows SUPER_ADMIN regardless of membership."""
        from unittest.mock import patch
        from app.auth.decorators import project_permission_required

        @project_permission_required("execution.trigger")
        def _view(id):
            return "ok"

        with app.test_request_context(f"/test/{owned_project.id}"):
            with patch("flask_login.utils._get_user", return_value=admin_user):
                result = _view(id=owned_project.id)
                assert result == "ok"
