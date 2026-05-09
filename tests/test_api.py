"""API endpoint tests with Bearer token authentication."""

from unittest.mock import MagicMock, patch

from app.models.api_token import ApiToken


class TestTokenAuthentication:
    """Tests for the Bearer token authentication decorator."""

    def test_missing_auth_header(self, client, db):
        """Request without Authorization header returns 401."""
        resp = client.get("/api/v1/projects")
        assert resp.status_code == 401
        data = resp.get_json()
        assert "error" in data

    def test_malformed_auth_header(self, client, db):
        """Request with malformed header returns 401."""
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Basic abc123"},
        )
        assert resp.status_code == 401

    def test_empty_bearer_token(self, client, db):
        """Request with empty Bearer token returns 401."""
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    def test_invalid_token(self, client, db):
        """Request with invalid token returns 401."""
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer qap_invalidtoken12345"},
        )
        assert resp.status_code == 401

    def test_revoked_token(self, client, db, api_token):
        """Request with revoked token returns 401."""
        token, raw = api_token
        token.revoke()

        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 401

    def test_valid_token_authenticates(self, client, db, api_token):
        """Request with valid token succeeds."""
        token, raw = api_token
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200


class TestProjectAPI:
    """Tests for /api/v1/projects endpoints."""

    def test_list_projects_empty(self, client, db, api_token):
        """GET /api/v1/projects returns empty list."""
        token, raw = api_token
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["projects"] == []

    def test_list_projects_with_data(self, client, db, api_token, sample_project):
        """GET /api/v1/projects returns projects."""
        token, raw = api_token
        resp = client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["projects"]) >= 1
        assert data["projects"][0]["name"] == "Test Project"

    def test_get_project_detail(self, client, db, api_token, sample_project):
        """GET /api/v1/projects/<id> returns project details."""
        token, raw = api_token
        resp = client.get(
            f"/api/v1/projects/{sample_project.id}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Test Project"
        assert "suites" in data

    def test_get_project_not_found(self, client, db, api_token):
        """GET /api/v1/projects/<id> with bad id returns 404."""
        token, raw = api_token
        resp = client.get(
            "/api/v1/projects/99999",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404


class TestExecutionAPI:
    """Tests for /api/v1/executions endpoint."""

    def test_create_execution_requires_project_id(self, client, db, api_token):
        """POST /api/v1/executions without project_id returns 400."""
        token, raw = api_token
        resp = client.post(
            "/api/v1/executions",
            json={},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "project_id" in data["error"].lower()

    def test_create_execution_project_not_found(self, client, db, api_token):
        """POST /api/v1/executions with invalid project_id returns 404."""
        token, raw = api_token
        resp = client.post(
            "/api/v1/executions",
            json={"project_id": 99999},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 404

    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    def test_create_execution_success(self, mock_pipeline, client, db, api_token, sample_project):
        """POST /api/v1/executions creates execution and returns 201."""
        token, raw = api_token
        mock_result = MagicMock()
        mock_result.id = "api-task-id"
        mock_pipeline.delay.return_value = mock_result

        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["project_id"] == sample_project.id
        assert data["status"] == "pending"
        assert data["celery_task_id"] == "api-task-id"

    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    def test_create_execution_with_suite(self, mock_pipeline, client, db, api_token, sample_project):
        """POST /api/v1/executions with suite_id."""
        from app.models.test_suite import TestSuite, TestType

        suite = TestSuite(
            project_id=sample_project.id,
            name="test_suite",
            path_in_repo="tests/test_suite.py",
            test_type=TestType.UNIT,
        )
        db.session.add(suite)
        db.session.commit()

        token, raw = api_token
        mock_result = MagicMock()
        mock_result.id = "suite-task"
        mock_pipeline.delay.return_value = mock_result

        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id, "suite_id": suite.id},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["suite_id"] == suite.id

    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    def test_create_execution_with_extra_args(self, mock_pipeline, client, db, api_token, sample_project):
        """POST /api/v1/executions with extra_args passes them through."""
        token, raw = api_token
        mock_result = MagicMock()
        mock_result.id = "args-task"
        mock_pipeline.delay.return_value = mock_result

        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id, "extra_args": "-k smoke"},
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert resp.status_code == 201

    def test_create_execution_missing_auth(self, client, db, sample_project):
        """POST /api/v1/executions without token returns 401."""
        resp = client.post(
            "/api/v1/executions",
            json={"project_id": sample_project.id},
        )
        assert resp.status_code == 401


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self, client):
        """GET /health returns 200 with status ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
