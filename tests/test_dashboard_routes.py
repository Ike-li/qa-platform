"""Tests for app/dashboard/routes.py -- dashboard route-level tests.

Covers: index, api_pass_rate, api_trends, api_queue,
        api_failures, api_global_overview.
"""

from unittest.mock import patch


# ===========================================================================
# Dashboard index
# ===========================================================================


class TestDashboardIndex:
    def test_index_requires_auth(self, client, db):
        """Unauthenticated access redirects to login."""
        resp = client.get("/dashboard/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_index_renders(self, client, login_as_admin, sample_project, db):
        """Authenticated user sees the dashboard."""
        resp = client.get("/dashboard/")
        assert resp.status_code == 200

    def test_index_empty_projects(self, client, login_as_admin, db):
        """Dashboard renders even with no projects."""
        resp = client.get("/dashboard/")
        assert resp.status_code == 200


# ===========================================================================
# API: Pass rate
# ===========================================================================


class TestAPIPassRate:
    @patch("app.dashboard.routes.get_pass_rate_data")
    def test_pass_rate_success(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """GET /dashboard/api/dashboard/pass-rate returns JSON."""
        mock_fn.return_value = {
            "pass_rate": 85.0,
            "total_tests": 20,
            "counts": {"passed": 17, "failed": 2, "skipped": 1, "error": 0},
        }
        resp = client.get(
            f"/dashboard/api/dashboard/pass-rate?project_id={sample_project.id}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["pass_rate"] == 85.0
        assert data["total_tests"] == 20
        mock_fn.assert_called_once_with(sample_project.id, 7)

    @patch("app.dashboard.routes.get_pass_rate_data")
    def test_pass_rate_custom_days(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Custom days parameter is passed through."""
        mock_fn.return_value = {"pass_rate": 0, "total_tests": 0, "counts": {}}
        resp = client.get(
            f"/dashboard/api/dashboard/pass-rate?project_id={sample_project.id}&days=30"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, 30)

    def test_pass_rate_missing_project_id(self, client, login_as_admin, db):
        """Missing project_id returns 400."""
        resp = client.get("/dashboard/api/dashboard/pass-rate")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    @patch("app.dashboard.routes.get_pass_rate_data")
    def test_pass_rate_days_clamped(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Days parameter is clamped to [1, 365]."""
        mock_fn.return_value = {"pass_rate": 0, "total_tests": 0, "counts": {}}
        resp = client.get(
            f"/dashboard/api/dashboard/pass-rate?project_id={sample_project.id}&days=999"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, 365)


# ===========================================================================
# API: Trends
# ===========================================================================


class TestAPITrends:
    @patch("app.dashboard.routes.get_trend_data")
    def test_trends_success(self, mock_fn, client, login_as_admin, sample_project, db):
        """GET /dashboard/api/dashboard/trends returns JSON."""
        mock_fn.return_value = {
            "labels": ["2026-05-08", "2026-05-09"],
            "pass_rates": [80.0, 90.0],
        }
        resp = client.get(
            f"/dashboard/api/dashboard/trends?project_id={sample_project.id}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["labels"]) == 2
        mock_fn.assert_called_once_with(sample_project.id, "daily", 30)

    def test_trends_missing_project_id(self, client, login_as_admin, db):
        """Missing project_id returns 400."""
        resp = client.get("/dashboard/api/dashboard/trends")
        assert resp.status_code == 400

    @patch("app.dashboard.routes.get_trend_data")
    def test_trends_weekly_granularity(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Weekly granularity is passed through."""
        mock_fn.return_value = {"labels": [], "pass_rates": []}
        resp = client.get(
            f"/dashboard/api/dashboard/trends?project_id={sample_project.id}&granularity=weekly"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, "weekly", 30)

    @patch("app.dashboard.routes.get_trend_data")
    def test_trends_invalid_granularity_fallback(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Invalid granularity falls back to daily."""
        mock_fn.return_value = {"labels": [], "pass_rates": []}
        resp = client.get(
            f"/dashboard/api/dashboard/trends?project_id={sample_project.id}&granularity=hourly"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, "daily", 30)

    @patch("app.dashboard.routes.get_trend_data")
    def test_trends_monthly_granularity(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Monthly granularity is passed through."""
        mock_fn.return_value = {"labels": [], "pass_rates": []}
        resp = client.get(
            f"/dashboard/api/dashboard/trends?project_id={sample_project.id}&granularity=monthly"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, "monthly", 30)


# ===========================================================================
# API: Queue
# ===========================================================================


class TestAPIQueue:
    @patch("app.dashboard.routes.get_queue_status")
    def test_queue_success(self, mock_fn, client, login_as_admin, db):
        """GET /dashboard/api/dashboard/queue returns JSON."""
        mock_fn.return_value = [
            {"id": 1, "status": "running", "project_name": "Test"},
        ]
        resp = client.get("/dashboard/api/dashboard/queue")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "queue" in data
        assert len(data["queue"]) == 1

    @patch("app.dashboard.routes.get_queue_status")
    def test_queue_empty(self, mock_fn, client, login_as_admin, db):
        """Empty queue returns empty list."""
        mock_fn.return_value = []
        resp = client.get("/dashboard/api/dashboard/queue")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["queue"] == []


# ===========================================================================
# API: Failures
# ===========================================================================


class TestAPIFailures:
    @patch("app.dashboard.routes.get_recent_failures")
    def test_failures_success(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """GET /dashboard/api/dashboard/failures returns JSON."""
        mock_fn.return_value = [
            {"id": 1, "test_name": "test_login", "status": "failed"},
        ]
        resp = client.get(
            f"/dashboard/api/dashboard/failures?project_id={sample_project.id}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "failures" in data
        assert len(data["failures"]) == 1
        mock_fn.assert_called_once_with(sample_project.id, 20)

    def test_failures_missing_project_id(self, client, login_as_admin, db):
        """Missing project_id returns 400."""
        resp = client.get("/dashboard/api/dashboard/failures")
        assert resp.status_code == 400

    @patch("app.dashboard.routes.get_recent_failures")
    def test_failures_custom_limit(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Custom limit parameter is passed through."""
        mock_fn.return_value = []
        resp = client.get(
            f"/dashboard/api/dashboard/failures?project_id={sample_project.id}&limit=50"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, 50)

    @patch("app.dashboard.routes.get_recent_failures")
    def test_failures_limit_clamped(
        self, mock_fn, client, login_as_admin, sample_project, db
    ):
        """Limit is clamped to [1, 100]."""
        mock_fn.return_value = []
        resp = client.get(
            f"/dashboard/api/dashboard/failures?project_id={sample_project.id}&limit=200"
        )
        assert resp.status_code == 200
        mock_fn.assert_called_once_with(sample_project.id, 100)


# ===========================================================================
# API: Global overview
# ===========================================================================


class TestAPIGlobalOverview:
    @patch("app.dashboard.routes.get_all_projects_health")
    @patch("app.dashboard.routes.get_global_overview")
    def test_overview_success(
        self, mock_overview, mock_health, client, login_as_admin, db
    ):
        """GET /dashboard/api/dashboard/overview returns JSON."""
        mock_overview.return_value = {
            "total_projects": 1,
            "active_executions": 0,
            "recent_pass_rate": 100.0,
        }
        mock_health.return_value = [
            {"id": 1, "name": "Test Project", "latest_pass_rate": 100.0},
        ]
        resp = client.get("/dashboard/api/dashboard/overview")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "overview" in data
        assert "projects" in data
        assert data["overview"]["total_projects"] == 1
