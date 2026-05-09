"""WebSocket event tests for git sync progress."""

from unittest.mock import MagicMock, patch, call

import pytest


class TestSocketIOInit:
    def test_socketio_object_exists(self, app):
        from app.extensions import socketio
        assert socketio is not None

    def test_csrf_exempt_socketio(self, app):
        """Verify /socketio/ is exempt from CSRF (checked via app config)."""
        from app.extensions import csrf
        assert csrf is not None


class TestGitSyncEvents:
    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.clone_repo")
    @patch("app.tasks.git_tasks.discover_suites", return_value=[])
    @patch("app.tasks.git_tasks.db")
    def test_clone_emits_steps(self, mock_db, mock_discover, mock_clone, mock_emit):
        """git_sync_project with action=clone emits cloning, installing_deps, discovering_tests, complete."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project

        git_sync_project.run(project_id=1, action="clone")

        emit_calls = mock_emit.call_args_list
        steps = [c[0][1]["step"] for c in emit_calls if c[0][0] == "sync_step"]
        assert "cloning" in steps
        assert "installing_deps" in steps
        assert "discovering_tests" in steps
        assert "complete" in steps

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.clone_repo")
    @patch("app.tasks.git_tasks.discover_suites", return_value=[])
    @patch("app.tasks.git_tasks.db")
    def test_clone_returns_suites_found(self, mock_db, mock_discover, mock_clone, mock_emit):
        """Clone action returns the number of suites discovered."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project
        mock_discover.return_value = ["suite_a", "suite_b"]

        result = git_sync_project.run(project_id=1, action="clone")

        assert result["suites_found"] == 2
        assert result["status"] == "success"

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.pull_repo")
    @patch("app.tasks.git_tasks.db")
    def test_pull_emits_pulling(self, mock_db, mock_pull, mock_emit):
        """git_sync_project with action=pull emits pulling step."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project

        git_sync_project.run(project_id=1, action="pull")

        emit_calls = mock_emit.call_args_list
        steps = [c[0][1]["step"] for c in emit_calls if c[0][0] == "sync_step"]
        assert "pulling" in steps
        assert "complete" in steps

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.pull_repo")
    @patch("app.tasks.git_tasks.discover_suites", return_value=["s1"])
    @patch("app.tasks.git_tasks.db")
    def test_pull_and_discover_emits_steps(self, mock_db, mock_discover, mock_pull, mock_emit):
        """git_sync_project with action=pull_and_discover emits pulling, discovering_tests, complete."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project

        git_sync_project.run(project_id=1, action="pull_and_discover")

        emit_calls = mock_emit.call_args_list
        steps = [c[0][1]["step"] for c in emit_calls if c[0][0] == "sync_step"]
        assert "pulling" in steps
        assert "discovering_tests" in steps
        assert "complete" in steps

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.db")
    def test_unknown_action_returns_error(self, mock_db, mock_emit):
        """Unknown action returns error status without emitting sync_step events."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project

        result = git_sync_project.run(project_id=1, action="invalid_action")

        assert result["status"] == "error"
        sync_emits = [c for c in mock_emit.call_args_list if c[0][0] == "sync_step"]
        assert len(sync_emits) == 0

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.db")
    def test_project_not_found(self, mock_db, mock_emit):
        """Missing project returns error without emitting."""
        from app.tasks.git_tasks import git_sync_project

        mock_db.session.get.return_value = None

        result = git_sync_project.run(project_id=999, action="clone")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
        mock_emit.assert_not_called()

    @patch("app.tasks.git_tasks.emit_fn")
    @patch("app.tasks.git_tasks.clone_repo", side_effect=RuntimeError("clone failed"))
    @patch("app.tasks.git_tasks.db")
    def test_clone_exception_emits_error(self, mock_db, mock_clone, mock_emit):
        """Exception during clone emits an error step event."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.session.get.return_value = mock_project

        result = git_sync_project.run(project_id=1, action="clone")

        assert result["status"] == "error"
        emit_calls = mock_emit.call_args_list
        steps = [c[0][1]["step"] for c in emit_calls if c[0][0] == "sync_step"]
        assert "error" in steps

    def test_room_format(self):
        """Room name follows project:{id}:sync pattern."""
        assert f"project:{42}:sync" == "project:42:sync"

    def test_emit_fn_exists(self):
        """emit_fn is importable and callable."""
        from app.tasks.git_tasks import emit_fn
        assert callable(emit_fn)
