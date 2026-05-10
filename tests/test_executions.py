"""Execution trigger tests with mocked Celery tasks."""

from unittest.mock import MagicMock, patch

from app.models.execution import Execution, ExecutionStatus


class TestExecutionList:
    """Tests for GET /executions/."""

    def test_list_requires_auth(self, client, db):
        """Unauthenticated users are redirected."""
        resp = client.get("/executions/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_list_requires_permission(self, client, login_as_visitor):
        """Visitors can view executions (execution.view)."""
        resp = client.get("/executions/")
        assert resp.status_code == 200

    def test_list_empty(self, client, login_as_admin):
        """Empty execution list returns 200."""
        resp = client.get("/executions/")
        assert resp.status_code == 200

    def test_list_with_filter(self, client, login_as_admin):
        """List supports project_id and status filters."""
        resp = client.get("/executions/?project_id=1&status=pending")
        assert resp.status_code == 200


class TestExecutionDetail:
    """Tests for GET /executions/<id>."""

    def test_detail_404(self, client, login_as_admin):
        """Nonexistent execution returns 404."""
        resp = client.get("/executions/99999")
        assert resp.status_code == 404

    def test_detail_with_execution(self, client, login_as_admin, sample_project, db):
        """Existing execution renders its detail page."""
        execution = Execution(
            project_id=sample_project.id,
            status=ExecutionStatus.PENDING,
        )
        db.session.add(execution)
        db.session.commit()

        resp = client.get(f"/executions/{execution.id}")
        assert resp.status_code == 200


class TestExecutionTrigger:
    """Tests for POST /executions/trigger/<project_id>."""

    def test_trigger_requires_permission(
        self, client, login_as_visitor, sample_project
    ):
        """Visitors cannot trigger executions (no execution.trigger)."""
        resp = client.get(
            f"/executions/trigger/{sample_project.id}", follow_redirects=False
        )
        assert resp.status_code == 403

    def test_trigger_form_renders(self, client, login_as_admin, sample_project):
        """Trigger form renders for admin."""
        resp = client.get(f"/executions/trigger/{sample_project.id}")
        assert resp.status_code == 200

    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    def test_trigger_creates_execution(
        self, mock_pipeline, client, login_as_admin, sample_project, db
    ):
        """Triggering creates a PENDING execution and dispatches Celery task."""
        mock_result = MagicMock()
        mock_result.id = "fake-celery-task-id"
        mock_pipeline.delay.return_value = mock_result

        resp = client.post(
            f"/executions/trigger/{sample_project.id}",
            data={
                "suite_id": "0",  # 0 means all suites
                "extra_args": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        execution = Execution.query.filter_by(project_id=sample_project.id).first()
        assert execution is not None
        assert execution.status == ExecutionStatus.PENDING
        assert execution.celery_task_id == "fake-celery-task-id"

    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    def test_trigger_with_extra_args(
        self, mock_pipeline, client, login_as_admin, sample_project, db
    ):
        """Trigger with extra args passes them through."""
        mock_result = MagicMock()
        mock_result.id = "fake-task-id-2"
        mock_pipeline.delay.return_value = mock_result

        resp = client.post(
            f"/executions/trigger/{sample_project.id}",
            data={
                "suite_id": "0",
                "extra_args": "-k smoke --timeout=60",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        execution = Execution.query.filter_by(project_id=sample_project.id).first()
        assert execution is not None
        assert execution.extra_args == "-k smoke --timeout=60"

    def test_trigger_nonexistent_project(self, client, login_as_admin):
        """Triggering against a nonexistent project returns 404."""
        resp = client.post(
            "/executions/trigger/99999",
            data={"suite_id": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 404

    def test_trigger_tester_can_trigger(
        self, client, login_as_tester, sample_project, db
    ):
        """Testers have execution.trigger permission."""
        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_result = MagicMock()
            mock_result.id = "tester-task"
            mock_pipeline.delay.return_value = mock_result

            resp = client.get(f"/executions/trigger/{sample_project.id}")
            assert resp.status_code == 200

    def test_trigger_lead_can_trigger(self, client, login_as_lead, sample_project, db):
        """Project leads have execution.trigger permission."""
        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_result = MagicMock()
            mock_result.id = "lead-task"
            mock_pipeline.delay.return_value = mock_result

            resp = client.get(f"/executions/trigger/{sample_project.id}")
            assert resp.status_code == 200


class TestExecutionListExtended:
    """Extended list tests for error and permission edge cases."""

    def test_list_invalid_status_filter(self, client, login_as_admin):
        """Invalid status enum value is caught and list returns 200."""
        resp = client.get("/executions/?status=invalid_enum")
        assert resp.status_code == 200

    @patch("flask_login.utils._get_user")
    def test_list_visitor_no_permission(self, mock_get_user, client, db):
        """User without execution.view permission gets 403."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.has_permission.return_value = False
        mock_get_user.return_value = mock_user

        resp = client.get("/executions/")
        assert resp.status_code == 403


class TestExecutionTriggerExtended:
    """Extended trigger tests for error and failure paths."""

    @patch(
        "app.executions.routes.prepare_execution", side_effect=ValueError("bad input")
    )
    def test_trigger_prepare_valueerror(
        self, mock_prepare, client, login_as_admin, sample_project, db
    ):
        """ValueError from prepare_execution is caught and flashed."""
        resp = client.post(
            f"/executions/trigger/{sample_project.id}",
            data={"suite_id": "0", "extra_args": ""},
        )
        assert resp.status_code == 200
        assert b"bad input" in resp.data

    @patch(
        "app.executions.routes.prepare_execution",
        side_effect=RuntimeError("connection lost"),
    )
    def test_trigger_prepare_generic_error(
        self, mock_prepare, client, login_as_admin, sample_project, db
    ):
        """Generic exception from prepare_execution is caught and flashed."""
        resp = client.post(
            f"/executions/trigger/{sample_project.id}",
            data={"suite_id": "0", "extra_args": ""},
        )
        assert resp.status_code == 200
        assert b"connection lost" in resp.data

    @patch("app.extensions.db.session.commit", side_effect=Exception("db down"))
    @patch("app.executions.routes.prepare_execution")
    def test_trigger_commit_failure(
        self, mock_prepare, mock_commit, client, login_as_admin, sample_project, db
    ):
        """Commit failure triggers rollback, re-raise, caught by outer handler."""
        mock_exec = MagicMock()
        mock_exec.id = 999
        mock_prepare.return_value = mock_exec

        with patch("app.tasks.execution_tasks.run_execution_pipeline") as mock_pipeline:
            mock_result = MagicMock()
            mock_result.id = "task-1"
            mock_pipeline.delay.return_value = mock_result

            resp = client.post(
                f"/executions/trigger/{sample_project.id}",
                data={"suite_id": "0", "extra_args": ""},
            )
            # Re-raised exception is caught by outer except -> flash + 200
            assert resp.status_code == 200
            assert b"db down" in resp.data
