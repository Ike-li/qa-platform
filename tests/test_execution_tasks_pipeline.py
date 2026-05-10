"""Tests for execution_tasks.py pipeline stages (stage_git_sync, stage_run_tests,
stage_generate_report, run_execution_pipeline edge case).

Targets lines 192-199, 225-226, 230, 329, 336-337, 361-365, 377-378,
417, 446-449, 464-465, 477-478, 502-506, 519-520 for coverage improvement.
"""

import subprocess as _real_subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.models.execution import ExecutionStatus
from app.tasks.execution_tasks import PipelineAbort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_execution(
    exec_id=1,
    project_id=10,
    status=ExecutionStatus.PENDING,
    is_terminal=False,
    extra_args=None,
    suite_id=None,
):
    exc = MagicMock()
    exc.id = exec_id
    exc.project_id = project_id
    exc.status = status
    exc.is_terminal = is_terminal
    exc.extra_args = extra_args
    exc.suite_id = suite_id
    return exc


def _make_project(project_id=10, repo_path="/tmp/repo", sandbox_network=None):
    proj = MagicMock()
    proj.id = project_id
    proj.repo_path = repo_path
    proj.git_url = "https://github.com/example/test.git"
    proj.git_branch = "main"
    proj.sandbox_network = sandbox_network
    proj.get_credential.return_value = None
    return proj


def _make_subprocess_mock():
    """Create a subprocess mock with real exception classes."""
    mock = MagicMock()
    mock.TimeoutExpired = _real_subprocess.TimeoutExpired
    mock.CalledProcessError = _real_subprocess.CalledProcessError
    return mock


# ---------------------------------------------------------------------------
# TestStageGitSync
# ---------------------------------------------------------------------------


class TestStageGitSync:
    """Tests for stage_git_sync error/edge paths."""

    @patch("app.tasks.execution_tasks.db")
    def test_execution_not_found(self, mock_db):
        from app.tasks.execution_tasks import stage_git_sync

        mock_db.session.get.return_value = None
        result = stage_git_sync.run(999)
        assert result == 999

    @patch(
        "app.tasks.execution_tasks._fail_execution",
        side_effect=PipelineAbort("no proj"),
    )
    @patch("app.tasks.execution_tasks.db")
    def test_project_not_found_fails(self, mock_db, mock_fail):
        from app.tasks.execution_tasks import stage_git_sync

        execution = _make_execution()
        mock_db.session.get.side_effect = (
            lambda model, eid: execution if eid == 1 else None
        )
        with pytest.raises(PipelineAbort):
            stage_git_sync.run(1)
        mock_fail.assert_called_once()

    @patch(
        "app.tasks.execution_tasks._fail_execution",
        side_effect=PipelineAbort("venv timeout"),
    )
    @patch(
        "app.tasks.execution_tasks._build_clone_url",
        return_value="https://github.com/x/t.git",
    )
    @patch("app.tasks.execution_tasks._cleanup_venv")
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv/1")
    @patch("app.tasks.execution_tasks.db")
    def test_venv_timeout_fails(
        self,
        mock_db,
        mock_venv_path,
        mock_set_status,
        mock_cleanup,
        mock_build,
        mock_fail,
    ):
        from app.tasks.execution_tasks import stage_git_sync

        execution = _make_execution()
        project = _make_project()

        def get_side_effect(model, eid):
            if hasattr(model, "__tablename__") and model.__tablename__ == "executions":
                return execution
            return project

        mock_db.session.get.side_effect = get_side_effect

        mock_sub = _make_subprocess_mock()
        git_ok = MagicMock()
        git_ok.stdout.strip.return_value = "abc123"
        mock_sub.run.side_effect = [
            MagicMock(),
            MagicMock(),
            git_ok,
            _real_subprocess.TimeoutExpired(cmd="python -m venv", timeout=120),
        ]

        with patch("app.tasks.execution_tasks.subprocess", mock_sub), patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=True
        ):
            with pytest.raises(PipelineAbort):
                stage_git_sync.run(1)
        mock_fail.assert_called_once()

    @patch(
        "app.tasks.execution_tasks._fail_execution",
        side_effect=PipelineAbort("venv err"),
    )
    @patch(
        "app.tasks.execution_tasks._build_clone_url",
        return_value="https://github.com/x/t.git",
    )
    @patch("app.tasks.execution_tasks._cleanup_venv")
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv/1")
    @patch("app.tasks.execution_tasks.db")
    def test_venv_generic_error_fails(
        self,
        mock_db,
        mock_venv_path,
        mock_set_status,
        mock_cleanup,
        mock_build,
        mock_fail,
    ):
        from app.tasks.execution_tasks import stage_git_sync

        execution = _make_execution()
        project = _make_project()

        def get_side_effect(model, eid):
            if hasattr(model, "__tablename__") and model.__tablename__ == "executions":
                return execution
            return project

        mock_db.session.get.side_effect = get_side_effect

        mock_sub = _make_subprocess_mock()
        git_ok = MagicMock()
        git_ok.stdout.strip.return_value = "abc123"
        mock_sub.run.side_effect = [
            MagicMock(),
            MagicMock(),
            git_ok,
            RuntimeError("venv exploded"),
        ]

        with patch("app.tasks.execution_tasks.subprocess", mock_sub), patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=True
        ):
            with pytest.raises(PipelineAbort):
                stage_git_sync.run(1)
        mock_fail.assert_called_once()


# ---------------------------------------------------------------------------
# TestStageRunTests
# ---------------------------------------------------------------------------


class TestStageRunTests:
    """Tests for stage_run_tests error/edge paths."""

    @patch("app.tasks.execution_tasks.db")
    def test_terminal_state_skips(self, mock_db):
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution(is_terminal=True, status=ExecutionStatus.COMPLETED)
        mock_db.session.get.return_value = execution
        result = stage_run_tests.run(1)
        assert result == 1

    @patch("app.tasks.execution_tasks._release_exec_slot")
    @patch("app.tasks.execution_tasks.db")
    def test_execution_not_found_after_acquire(self, mock_db, mock_release):
        from app.tasks.execution_tasks import stage_run_tests

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                None,
            ]
            result = stage_run_tests.run(1)
        assert result == 1
        mock_release.assert_called_once_with(1)

    @patch("app.tasks.execution_tasks._results_dir", return_value="/tmp/results")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv")
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks.db")
    def test_disallowed_flag_raises(
        self, mock_db, mock_set_status, mock_venv, mock_results
    ):
        """ValueError raised for disallowed pytest flag (not wrapped in _fail_execution)."""
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution(extra_args="--fork")
        project = _make_project()

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                execution,
                project,
            ]
            with patch(
                "app.tasks.execution_tasks.os.path.isfile", return_value=True
            ), patch("app.tasks.execution_tasks.os.makedirs"):
                with pytest.raises(ValueError, match="Disallowed pytest argument"):
                    stage_run_tests.run(1)

    @patch.dict(sys.modules, {"docker": MagicMock()})
    @patch("app.tasks.execution_tasks._results_dir", return_value="/tmp/results")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv")
    @patch(
        "app.tasks.execution_tasks._fail_execution", side_effect=PipelineAbort("cfg")
    )
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks.db")
    def test_sandbox_config_error(
        self, mock_db, mock_set_status, mock_fail, mock_venv, mock_results
    ):
        """Calls _fail_execution when SandboxConfigError is raised."""
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution()
        # sandbox_network must be non-None to avoid SystemConfig.get path
        project = _make_project(sandbox_network=False)

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                execution,
                project,
            ]

            SandboxConfigError = type("SandboxConfigError", (Exception,), {})
            SandboxRuntimeError = type("SandboxRuntimeError", (Exception,), {})
            mock_runner_cls = MagicMock()
            mock_runner_cls.return_value.run.side_effect = SandboxConfigError(
                "config bad"
            )

            sandbox_mod = MagicMock()
            sandbox_mod.SandboxRunner = mock_runner_cls
            sandbox_mod.SandboxConfigError = SandboxConfigError
            sandbox_mod.SandboxRuntimeError = SandboxRuntimeError

            with patch.dict(sys.modules, {"app.tasks.sandbox": sandbox_mod}), patch(
                "app.tasks.execution_tasks.os.path.isfile", return_value=True
            ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
                "app.tasks.execution_tasks.os.environ", {}
            ), patch(
                "app.tasks.execution_tasks.os.getenv",
                side_effect=lambda k, d=None: "true" if k == "ENABLE_SANDBOX" else d,
            ):
                with pytest.raises(PipelineAbort):
                    stage_run_tests.run(1)
        mock_fail.assert_called()

    @patch.dict(sys.modules, {"docker": MagicMock()})
    @patch("app.tasks.execution_tasks._results_dir", return_value="/tmp/results")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv")
    @patch(
        "app.tasks.execution_tasks._fail_execution",
        side_effect=PipelineAbort("runtime"),
    )
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks.db")
    def test_sandbox_runtime_error(
        self, mock_db, mock_set_status, mock_fail, mock_venv, mock_results
    ):
        """Calls _fail_execution when SandboxRuntimeError is raised."""
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution()
        project = _make_project(sandbox_network=False)

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                execution,
                project,
            ]

            SandboxConfigError = type("SandboxConfigError", (Exception,), {})
            SandboxRuntimeError = type("SandboxRuntimeError", (Exception,), {})
            mock_runner_instance = MagicMock()
            mock_runner_instance.run.side_effect = SandboxRuntimeError("runtime bad")
            mock_runner_cls = MagicMock(return_value=mock_runner_instance)

            sandbox_mod = MagicMock()
            sandbox_mod.SandboxRunner = mock_runner_cls
            sandbox_mod.SandboxConfigError = SandboxConfigError
            sandbox_mod.SandboxRuntimeError = SandboxRuntimeError

            with patch.dict(sys.modules, {"app.tasks.sandbox": sandbox_mod}), patch(
                "app.tasks.execution_tasks.os.path.isfile", return_value=True
            ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
                "app.tasks.execution_tasks.os.environ", {}
            ), patch(
                "app.tasks.execution_tasks.os.getenv",
                side_effect=lambda k, d=None: "true" if k == "ENABLE_SANDBOX" else d,
            ):
                with pytest.raises(PipelineAbort):
                    stage_run_tests.run(1)
        mock_fail.assert_called()

    @patch("app.tasks.execution_tasks._results_dir", return_value="/tmp/results")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv")
    @patch(
        "app.tasks.execution_tasks._fail_execution",
        side_effect=PipelineAbort("sub err"),
    )
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks.db")
    def test_subprocess_exception(
        self, mock_db, mock_set_status, mock_fail, mock_venv, mock_results
    ):
        """Calls _fail_execution when subprocess.run raises Exception."""
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution()
        project = _make_project()

        mock_sub = _make_subprocess_mock()
        mock_sub.run.side_effect = RuntimeError("subprocess boom")

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                execution,
                project,
            ]
            with patch("app.tasks.execution_tasks.subprocess", mock_sub), patch(
                "app.tasks.execution_tasks.os.path.isfile", return_value=True
            ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
                "app.tasks.execution_tasks.os.getenv",
                side_effect=lambda k, d=None: "false" if k == "ENABLE_SANDBOX" else d,
            ):
                with pytest.raises(PipelineAbort):
                    stage_run_tests.run(1)
        mock_fail.assert_called()

    @patch(
        "app.executions.services.parse_pytest_output",
        side_effect=Exception("parse error"),
    )
    @patch("app.tasks.execution_tasks._results_dir", return_value="/tmp/results")
    @patch("app.tasks.execution_tasks._venv_path", return_value="/tmp/venv")
    @patch("app.tasks.execution_tasks._set_status")
    @patch("app.tasks.execution_tasks._release_exec_slot")
    @patch("app.tasks.execution_tasks.db")
    def test_junit_parse_error_continues(
        self,
        mock_db,
        mock_release,
        mock_set_status,
        mock_venv,
        mock_results,
        mock_parse,
    ):
        from app.tasks.execution_tasks import stage_run_tests

        execution = _make_execution()
        project = _make_project()

        mock_sub = _make_subprocess_mock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "all passed"
        mock_result.stderr = ""
        mock_sub.run.return_value = mock_result

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                execution,
                project,
            ]
            with patch("app.tasks.execution_tasks.subprocess", mock_sub), patch(
                "app.tasks.execution_tasks.os.path.isfile", return_value=True
            ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
                "app.tasks.execution_tasks.os.getenv",
                side_effect=lambda k, d=None: "false" if k == "ENABLE_SANDBOX" else d,
            ):
                result = stage_run_tests.run(1)

        assert result == 1
        mock_release.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# TestStageGenerateReport
# ---------------------------------------------------------------------------


class TestStageGenerateReport:
    """Tests for stage_generate_report edge paths."""

    @patch("app.tasks.execution_tasks.db")
    def test_terminal_state_skips(self, mock_db):
        from app.tasks.execution_tasks import stage_generate_report

        execution = _make_execution(is_terminal=True, status=ExecutionStatus.COMPLETED)
        mock_db.session.get.return_value = execution
        result = stage_generate_report.run(1)
        assert result == 1

    @patch("app.tasks.execution_tasks._release_exec_slot")
    @patch("app.tasks.execution_tasks.db")
    def test_execution_not_found_after_acquire(self, mock_db, mock_release):
        from app.tasks.execution_tasks import stage_generate_report

        with patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True):
            mock_db.session.get.side_effect = [
                _make_execution(is_terminal=False),
                None,
            ]
            result = stage_generate_report.run(1)
        assert result == 1
        mock_release.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# TestRunExecutionPipelineNoSlot
# ---------------------------------------------------------------------------


class TestRunExecutionPipelineNoSlot:
    """Test for run_execution_pipeline when no slot acquired and execution not found."""

    @patch("app.tasks.execution_tasks.chain")
    @patch("app.tasks.execution_tasks._fail_execution")
    @patch("app.tasks.execution_tasks.db")
    @patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=False)
    def test_no_slot_no_execution_found(
        self, mock_acquire, mock_db, mock_fail, mock_chain
    ):
        """Returns execution_id when no slot acquired AND execution not found."""
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_db.session.get.return_value = None
        mock_pipeline = MagicMock()
        mock_chain.return_value = mock_pipeline
        result = run_execution_pipeline.run(42)
        assert result == 42
        mock_fail.assert_not_called()
