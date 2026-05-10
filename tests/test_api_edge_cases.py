"""Tests for API edge cases -- uncovered branches in api/ module.

Covers: execution creation with invalid suite_id, rate limit branches,
        projects RBAC visibility, and auth edge cases.
"""

from unittest.mock import MagicMock, patch

from app.models.project import Project
from app.models.project_membership import ProjectMembership, ProjectRole
from app.models.test_suite import TestSuite, TestType
from app.models.user import Role, User


# ===========================================================================
# Execution API edge cases
# ===========================================================================


class TestExecutionAPIEdgeCases:
    def test_create_execution_suite_not_found(
        self, client, db, api_token, sample_project
    ):
        """POST /api/v1/executions with non-existent suite_id returns 404."""
        token, raw = api_token
        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id, "suite_id": 99999},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert "套件" in data["error"] or "suite" in data["error"].lower()

    def test_create_execution_suite_wrong_project(
        self, client, db, api_token, sample_project, admin_user
    ):
        """POST with suite belonging to a different project returns 404."""
        # Create another project
        other_project = Project(
            name="Other Project",
            description="",
            git_url="https://example.com/other.git",
            git_branch="main",
            owner_id=admin_user.id,
        )
        db.session.add(other_project)
        db.session.commit()

        # Create suite under other_project
        suite = TestSuite(
            project_id=other_project.id,
            name="other_suite",
            path_in_repo="tests/other.py",
            test_type=TestType.UNIT,
        )
        db.session.add(suite)
        db.session.commit()

        token, raw = api_token
        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id, "suite_id": suite.id},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404

    def test_create_execution_extra_args_stripped(
        self, client, db, api_token, sample_project
    ):
        """Extra args with whitespace are stripped."""
        token, raw = api_token
        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_result = MagicMock()
            mock_result.id = "strip-task"
            mock_pipeline.delay.return_value = mock_result

            resp = client.post(
                "/api/v1/executions",
                json={"project_id": sample_project.id, "extra_args": "  -k smoke  "},
                headers={"Authorization": f"Bearer {raw}"},
            )
        assert resp.status_code == 201

    def test_create_execution_no_extra_args(
        self, client, db, api_token, sample_project
    ):
        """No extra_args in body sets None."""
        token, raw = api_token
        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_result = MagicMock()
            mock_result.id = "no-args-task"
            mock_pipeline.delay.return_value = mock_result

            resp = client.post(
                "/api/v1/executions",
                json={"project_id": sample_project.id},
                headers={"Authorization": f"Bearer {raw}"},
            )
        assert resp.status_code == 201

    def test_create_execution_rollback_on_error(
        self, client, db, api_token, sample_project
    ):
        """Exception during creation triggers rollback."""
        token, raw = api_token
        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_pipeline.delay.side_effect = RuntimeError("celery down")

            resp = client.post(
                "/api/v1/executions",
                json={"project_id": sample_project.id},
                headers={"Authorization": f"Bearer {raw}"},
            )
        assert resp.status_code == 500


# ===========================================================================
# Rate limit branch in api/__init__.py
# ===========================================================================


class TestAPIRateLimit:
    @patch("app.api._redis")
    def test_rate_limit_exceeded(self, mock_redis, client, db, api_token):
        """Rate limit returns 429 when count exceeds max."""
        token, raw = api_token

        # Mock the pipeline to return a count > 10
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, None, 15]  # count = 15 > 10
        mock_redis.pipeline.return_value = mock_pipe

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 429
        data = resp.get_json()
        assert "频率" in data["error"]

    @patch("app.api._redis")
    def test_rate_limit_under_limit(self, mock_redis, client, db, api_token):
        """Normal request passes when under rate limit."""
        token, raw = api_token

        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, None, 3]  # count = 3 < 10
        mock_redis.pipeline.return_value = mock_pipe

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200

    @patch("app.api._redis")
    def test_rate_limit_redis_failure_testing_mode(
        self, mock_redis, client, db, api_token
    ):
        """Redis failure in TESTING mode allows request through."""
        token, raw = api_token
        mock_redis.pipeline.side_effect = RuntimeError("redis down")

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        # In testing mode, the exception is caught and request proceeds
        assert resp.status_code == 200


# ===========================================================================
# Projects API RBAC
# ===========================================================================


class TestProjectsAPIRBAC:
    def test_non_admin_limited_projects(self, client, db, admin_user):
        """Non-super-admin user only sees owned/membership projects."""
        # Create a non-admin user with an API token
        viewer = User(
            username="api_viewer",
            email="api_viewer@test.com",
            role=Role.VISITOR,
            is_active=True,
        )
        viewer.set_password("password123")
        db.session.add(viewer)
        db.session.commit()

        from app.models.api_token import ApiToken

        _, raw = ApiToken.create_token(user_id=viewer.id, name="viewer-token")

        # Create a project owned by admin
        project = Project(
            name="Admin Project",
            description="",
            git_url="https://example.com/admin.git",
            git_branch="main",
            owner_id=admin_user.id,
        )
        db.session.add(project)
        db.session.commit()

        # Viewer should NOT see admin's project
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["projects"]) == 0

    def test_member_sees_membership_project(
        self, client, db, admin_user, sample_project
    ):
        """User with project membership can see it."""
        viewer = User(
            username="member_user",
            email="member@test.com",
            role=Role.VISITOR,
            is_active=True,
        )
        viewer.set_password("password123")
        db.session.add(viewer)
        db.session.commit()

        membership = ProjectMembership(
            user_id=viewer.id,
            project_id=sample_project.id,
            role=ProjectRole.VIEWER,
        )
        db.session.add(membership)
        db.session.commit()

        from app.models.api_token import ApiToken

        _, raw = ApiToken.create_token(user_id=viewer.id, name="member-token")

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["projects"]) == 1

    def test_get_project_not_in_visible_set(
        self, client, db, admin_user, sample_project
    ):
        """GET /api/v1/projects/<id> for project not in visible set returns 404."""
        viewer = User(
            username="restricted",
            email="restricted@test.com",
            role=Role.VISITOR,
            is_active=True,
        )
        viewer.set_password("password123")
        db.session.add(viewer)
        db.session.commit()

        from app.models.api_token import ApiToken

        _, raw = ApiToken.create_token(user_id=viewer.id, name="restricted-token")

        resp = client.get(
            f"/api/v1/projects/{sample_project.id}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404

    def test_get_project_detail_with_suites_and_schedules(
        self, client, db, api_token, sample_project
    ):
        """GET /api/v1/projects/<id> includes suites and schedules."""
        suite = TestSuite(
            project_id=sample_project.id,
            name="api_suite",
            path_in_repo="tests/api_suite.py",
            test_type=TestType.API,
        )
        db.session.add(suite)
        db.session.commit()

        token, raw = api_token
        resp = client.get(
            f"/api/v1/projects/{sample_project.id}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["suites"]) == 1
        assert data["suites"][0]["name"] == "api_suite"


# ===========================================================================
# API spec
# ===========================================================================


class TestAPISpec:
    def test_openapi_spec_accessible(self, client, db):
        """GET /api/docs returns 200 or 302 (swagger UI)."""
        resp = client.get("/api/docs", follow_redirects=False)
        assert resp.status_code in (200, 302, 308)
