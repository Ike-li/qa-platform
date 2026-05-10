"""Unit tests for git_tasks.py module-level functions.

Covers: emit_fn, _run_git_stream, git_sync_project (all action branches + errors).
"""

from unittest.mock import MagicMock, patch

import pytest


class TestEmitFn:
    """Tests for emit_fn."""

    @patch("app.tasks.git_tasks._worker_socketio")
    def test_calls_emit_with_event_data_room(self, mock_sio):
        """Calls _worker_socketio.emit with event, data, and room kwargs."""
        from app.tasks.git_tasks import emit_fn

        emit_fn("test_event", {"key": "value"}, room="room1")

        mock_sio.emit.assert_called_once_with(
            "test_event", {"key": "value"}, room="room1"
        )

    @patch("app.tasks.git_tasks._worker_socketio")
    def test_calls_emit_without_room(self, mock_sio):
        """Calls _worker_socketio.emit without room when not provided."""
        from app.tasks.git_tasks import emit_fn

        emit_fn("test_event", {"key": "value"})

        mock_sio.emit.assert_called_once_with("test_event", {"key": "value"}, room=None)


class TestRunGitStream:
    """Tests for _run_git_stream."""

    @patch("app.tasks.git_tasks.subprocess.Popen")
    def test_success_emits_lines(self, mock_popen_cls):
        """Emits each stdout line and returns on zero exit."""
        from app.tasks.git_tasks import _run_git_stream

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n", "line2\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen_cls.return_value = mock_proc

        mock_emit = MagicMock()

        result = _run_git_stream(["status"], "/tmp", emit_fn=mock_emit, room="room1")

        assert result.returncode == 0
        assert mock_emit.call_count == 2
        mock_emit.assert_any_call("git_output", {"line": "line1"}, room="room1")
        mock_emit.assert_any_call("git_output", {"line": "line2"}, room="room1")

    @patch("app.tasks.git_tasks.subprocess.Popen")
    def test_nonzero_exit_raises(self, mock_popen_cls):
        """Raises RuntimeError on non-zero exit code."""
        from app.tasks.git_tasks import _run_git_stream

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["error output\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        mock_popen_cls.return_value = mock_proc

        with pytest.raises(RuntimeError, match="failed"):
            _run_git_stream(["pull"], "/tmp", emit_fn=MagicMock(), room="room1")

    @patch("app.tasks.git_tasks.subprocess.Popen")
    def test_kills_proc_on_exception(self, mock_popen_cls):
        """Calls proc.kill() when exception occurs during iteration."""
        from app.tasks.git_tasks import _run_git_stream

        mock_proc = MagicMock()

        def failing_iter():
            yield "line1\n"
            raise IOError("broken pipe")

        mock_proc.stdout = failing_iter()
        mock_proc.kill = MagicMock()
        mock_popen_cls.return_value = mock_proc

        with pytest.raises(IOError):
            _run_git_stream(["pull"], "/tmp", emit_fn=MagicMock(), room="room1")

        mock_proc.kill.assert_called_once()


class TestGitSyncProject:
    """Tests for git_sync_project task."""

    @patch("app.tasks.git_tasks.discover_suites")
    @patch("app.tasks.git_tasks.clone_repo")
    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_clone_action_success(self, mock_emit, mock_db, mock_clone, mock_discover):
        """Clone action returns success with suites_found."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project
        mock_discover.return_value = ["suite1", "suite2"]

        result = git_sync_project.run(1, action="clone")

        assert result["status"] == "success"
        assert result["action"] == "clone"
        assert result["suites_found"] == 2
        mock_clone.assert_called_once_with(mock_project)
        mock_discover.assert_called_once_with(mock_project)

        # Verify emit order
        calls = mock_emit.call_args_list
        steps = [c.args[1]["step"] for c in calls if c.args[0] == "sync_step"]
        assert steps == ["cloning", "installing_deps", "discovering_tests", "complete"]

    @patch("app.tasks.git_tasks.pull_repo")
    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_pull_action_success(self, mock_emit, mock_db, mock_pull):
        """Pull action returns success with output."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project
        mock_pull.return_value = "Already up to date."

        result = git_sync_project.run(1, action="pull")

        assert result["status"] == "success"
        assert result["action"] == "pull"
        assert result["output"] == "Already up to date."
        mock_pull.assert_called_once_with(mock_project)

    @patch("app.tasks.git_tasks.discover_suites")
    @patch("app.tasks.git_tasks.pull_repo")
    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_pull_and_discover_success(
        self, mock_emit, mock_db, mock_pull, mock_discover
    ):
        """Pull and discover action returns success with suites_found."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project
        mock_discover.return_value = ["suite1"]

        result = git_sync_project.run(1, action="pull_and_discover")

        assert result["status"] == "success"
        assert result["action"] == "pull_and_discover"
        assert result["suites_found"] == 1
        mock_pull.assert_called_once_with(mock_project)
        mock_discover.assert_called_once_with(mock_project)

    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_unknown_action(self, mock_emit, mock_db):
        """Unknown action returns error dict."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project

        result = git_sync_project.run(1, action="invalid")

        assert result["status"] == "error"
        assert "Unknown action" in result["message"]

    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_project_not_found(self, mock_emit, mock_db):
        """Returns error when project not found."""
        from app.tasks.git_tasks import git_sync_project

        mock_db.session.get.return_value = None

        result = git_sync_project.run(999, action="clone")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @patch("app.tasks.git_tasks.clone_repo", side_effect=RuntimeError("clone failed"))
    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_clone_exception_returns_error(self, mock_emit, mock_db, mock_clone):
        """Exception during clone returns error dict and emits error step."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project

        result = git_sync_project.run(1, action="clone")

        assert result["status"] == "error"
        assert "clone failed" in result["message"]
        # Verify emit_fn called with error step
        error_calls = [
            c
            for c in mock_emit.call_args_list
            if c.args[0] == "sync_step" and c.args[1].get("step") == "error"
        ]
        assert len(error_calls) == 1

    @patch("app.tasks.git_tasks.discover_suites")
    @patch("app.tasks.git_tasks.pull_repo", side_effect=RuntimeError("pull failed"))
    @patch("app.tasks.git_tasks.db")
    @patch("app.tasks.git_tasks.emit_fn")
    def test_pull_and_discover_exception(
        self, mock_emit, mock_db, mock_pull, mock_discover
    ):
        """Exception during pull_and_discover returns error dict."""
        from app.tasks.git_tasks import git_sync_project

        mock_project = MagicMock()
        mock_db.session.get.return_value = mock_project

        result = git_sync_project.run(1, action="pull_and_discover")

        assert result["status"] == "error"
        assert "pull failed" in result["message"]
        mock_discover.assert_not_called()  # Should not reach discover
