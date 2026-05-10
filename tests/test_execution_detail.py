"""Comprehensive tests for app.tasks.execution_tasks.

Covers: slot management, pipeline entry, all three stages, and helpers.
Every test patches the module-level _redis to avoid a real Redis connection.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.models.execution import Execution, ExecutionStatus, TriggerType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_redis():
    """Patch the module-level _redis so no real Redis is needed."""
    mock = MagicMock()
    mock.scard.return_value = 0
    mock.sadd.return_value = 1
    mock.set.return_value = True
    mock.srem.return_value = 1
    mock.delete.return_value = 1
    mock.smembers.return_value = set()
    mock.exists.return_value = False
    pipe = MagicMock()
    mock.pipeline.return_value = pipe
    pipe.watch.return_value = None
    pipe.execute.return_value = [1, True]
    with patch("app.tasks.execution_tasks._redis", mock):
        yield mock


@pytest.fixture(autouse=True)
def _app_config(app):
    """Ensure app config has the execution directories."""
    app.config["EXECUTION_VENV_DIR"] = "/tmp/test-venvs"
    app.config["EXECUTION_RESULTS_DIR"] = "/tmp/test-results"
    app.config["REPO_DIR"] = "/tmp/test-repos"
    yield


@pytest.fixture
def execution(db, sample_project):
    ex = Execution(
        project_id=sample_project.id,
        status=ExecutionStatus.PENDING,
        trigger_type=TriggerType.WEB,
    )
    db.session.add(ex)
    db.session.commit()
    return ex


# ===================================================================
# Slot management tests
# ===================================================================


class TestSlotManagement:
    def test_acquire_slot_success(self, mock_redis):
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_redis.pipeline.return_value.watch.return_value = None
        mock_redis.scard.return_value = 0
        mock_redis.pipeline.return_value.execute.return_value = [1, True]
        assert _acquire_exec_slot(1) is True

    def test_acquire_slot_max_reached(self, mock_redis):
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_redis.scard.return_value = 100
        assert _acquire_exec_slot(99) is False

    def test_release_slot(self, mock_redis):
        from app.tasks.execution_tasks import _release_exec_slot

        _release_exec_slot(42)
        mock_redis.srem.assert_called_once_with("exec_slots", "42")
        mock_redis.delete.assert_called_once_with("exec_slot_ttl:42")

    def test_recover_stale_slots(self, mock_redis):
        from app.tasks.execution_tasks import _recover_stale_slots

        mock_redis.smembers.return_value = [b"1", b"2"]
        mock_redis.exists.side_effect = lambda k: k != "exec_slot_ttl:2"
        _recover_stale_slots()
        mock_redis.srem.assert_called_once_with("exec_slots", b"2")

    def test_on_worker_init_calls_recover(self, mock_redis):
        from app.tasks.execution_tasks import _on_worker_init

        _on_worker_init()
        mock_redis.smembers.assert_called_once()

    def test_get_max_slots_from_config(self, app):
        from app.models.system_config import SystemConfig
        from app.extensions import db as _db

        SystemConfig(key="max_exec_slots", value="7", value_type="int")
        cfg = SystemConfig(key="max_exec_slots", value="7", value_type="int")
        _db.session.add(cfg)
        _db.session.commit()
        from app.tasks.execution_tasks import _get_max_slots

        assert _get_max_slots() == 7

    def test_get_max_slots_default_on_error(self):
        from app.tasks.execution_tasks import _get_max_slots

        with patch.dict("sys.modules", {"app.models.system_config": None}):
            assert _get_max_slots() == 3


# ===================================================================
# Pipeline entry tests
# ===================================================================


class TestPipelineEntry:
    def test_run_execution_pipeline_success(self, mock_redis, execution, app):
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_redis.scard.return_value = 0
        with patch("app.tasks.execution_tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async.return_value = None
            result = run_execution_pipeline(execution.id)
        assert result == execution.id

    def test_run_execution_pipeline_no_slot(self, mock_redis, execution, app):
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_redis.scard.return_value = 100
        # _fail_execution raises PipelineAbort, caught inside the task
        result = run_execution_pipeline(execution.id)
        assert result == execution.id

    def test_run_execution_pipeline_dispatch_error(self, mock_redis, execution, app):
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_redis.scard.return_value = 0
        with patch("app.tasks.execution_tasks.chain") as mock_chain:
            mock_chain.return_value.apply_async.side_effect = RuntimeError(
                "broker down"
            )
            with pytest.raises(RuntimeError):
                run_execution_pipeline(execution.id)


# ===================================================================
# stage_git_sync tests
# ===================================================================


class TestStageGitSync:
    def test_clone_new_repo(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.makedirs"
        ), patch("app.tasks.execution_tasks.os.path.isfile", return_value=False), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ):

            def run_side_effect(cmd, **kwargs):
                if "clone" in cmd:
                    return MagicMock(returncode=0, stdout="", stderr="")
                if "rev-parse" in cmd:
                    return MagicMock(returncode=0, stdout="abc123\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = run_side_effect
            result = stage_git_sync(execution.id)
        assert result == execution.id

    def test_pull_existing_repo(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync

        with patch("app.tasks.execution_tasks.os.path.isdir", return_value=True), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=False
        ), patch("app.tasks.execution_tasks.shutil.rmtree"):

            def run_side_effect(cmd, **kwargs):
                if "rev-parse" in cmd:
                    return MagicMock(returncode=0, stdout="def456\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = run_side_effect
            result = stage_git_sync(execution.id)
        assert result == execution.id

    def test_git_timeout(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync, PipelineAbort

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.makedirs"
        ), patch("app.tasks.execution_tasks.shutil.rmtree"):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=300)
            with pytest.raises(PipelineAbort):
                stage_git_sync(execution.id)

    def test_git_failure(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync, PipelineAbort

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.makedirs"
        ), patch("app.tasks.execution_tasks.shutil.rmtree"):
            mock_run.side_effect = subprocess.CalledProcessError(
                128, "git", stderr="not found"
            )
            with pytest.raises(PipelineAbort):
                stage_git_sync(execution.id)

    def test_venv_setup_success(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.os.path.isfile", return_value=False), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ):

            def run_side_effect(cmd, **kwargs):
                if "rev-parse" in cmd:
                    return MagicMock(returncode=0, stdout="sha\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = run_side_effect
            result = stage_git_sync(execution.id)
        assert result == execution.id

    def test_venv_setup_failure(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync, PipelineAbort

        def run_side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return MagicMock(returncode=0, stdout="sha\n", stderr="")
            if "venv" in cmd:
                raise subprocess.CalledProcessError(
                    1, "python -m venv", stderr="cannot create"
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.os.path.isfile", return_value=False), patch(
            "app.tasks.execution_tasks.subprocess.run", side_effect=run_side_effect
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ):
            with pytest.raises(PipelineAbort):
                stage_git_sync(execution.id)

    def test_requirements_install(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_git_sync

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.os.path.isfile", return_value=True), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ):

            def run_side_effect(cmd, **kwargs):
                if "rev-parse" in cmd:
                    return MagicMock(returncode=0, stdout="sha\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = run_side_effect
            result = stage_git_sync(execution.id)
        assert result == execution.id
        pip_calls = [
            c for c in mock_run.call_args_list if any("pip" in str(a) for a in c[0])
        ]
        assert len(pip_calls) >= 1

    def test_sets_started_at_and_cloned_status(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_git_sync
        from app.extensions import db as _db

        with patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.os.path.isfile", return_value=False), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ):

            def run_side_effect(cmd, **kwargs):
                if "rev-parse" in cmd:
                    return MagicMock(returncode=0, stdout="sha\n", stderr="")
                return MagicMock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = run_side_effect
            stage_git_sync(execution.id)
        _db.session.refresh(execution)
        assert execution.started_at is not None
        assert execution.status == ExecutionStatus.CLONED


# ===================================================================
# stage_run_tests tests
# ===================================================================


class TestStageRunTests:
    def test_run_tests_success(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_run_tests
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.executions.services.parse_pytest_output"):
            mock_run.return_value = MagicMock(
                returncode=0, stdout="collected 5", stderr=""
            )
            result = stage_run_tests(execution.id)
        _db.session.refresh(execution)
        assert result == execution.id
        assert execution.status == ExecutionStatus.EXECUTED

    def test_run_tests_pytest_not_found(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_run_tests, PipelineAbort
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        _db.session.commit()
        with patch("app.tasks.execution_tasks.os.path.isfile", return_value=False):
            with pytest.raises(PipelineAbort):
                stage_run_tests(execution.id)

    def test_run_tests_timeout(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_run_tests, PipelineAbort
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pytest", 1800),
        ):
            with pytest.raises(PipelineAbort):
                stage_run_tests(execution.id)

    def test_run_tests_extra_args_valid(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_run_tests
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        execution.extra_args = "-v --tb long -k test_login"
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.executions.services.parse_pytest_output"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = stage_run_tests(execution.id)
        _db.session.refresh(execution)
        assert result == execution.id
        cmd = mock_run.call_args[0][0]
        assert "-v" in cmd
        assert "--tb" in cmd
        assert "long" in cmd
        assert "-k" in cmd
        assert "test_login" in cmd

    def test_run_tests_extra_args_rejected(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_run_tests
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        execution.extra_args = "--dangerous-flag"
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ):
            with pytest.raises(ValueError, match="Disallowed"):
                stage_run_tests(execution.id)

    def test_run_tests_no_suite(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_run_tests
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        execution.suite_id = None
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.executions.services.parse_pytest_output"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = stage_run_tests(execution.id)
        assert result == execution.id

    def test_run_tests_with_suite(self, mock_redis, db, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_run_tests
        from app.models.test_suite import TestSuite

        suite = TestSuite(
            project_id=sample_project.id, name="api", path_in_repo="tests/api"
        )
        db.session.add(suite)
        db.session.commit()
        execution.status = ExecutionStatus.CLONED
        execution.suite_id = suite.id
        db.session.commit()
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch(
            "app.tasks.execution_tasks.subprocess.run"
        ) as mock_run, patch("app.executions.services.parse_pytest_output"):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = stage_run_tests(execution.id)
        assert result == execution.id
        cmd = mock_run.call_args[0][0]
        assert any("tests/api" in c for c in cmd)

    def test_run_tests_sandbox_enabled(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_run_tests
        from app.extensions import db as _db

        execution.status = ExecutionStatus.CLONED
        _db.session.commit()
        mock_runner = MagicMock()
        mock_runner.run.return_value = {"return_code": 0, "stdout": "", "stderr": ""}
        mock_sandbox = MagicMock()
        mock_sandbox.SandboxRunner = MagicMock(return_value=mock_runner)
        mock_sandbox.SandboxConfigError = type("SandboxConfigError", (Exception,), {})
        mock_sandbox.SandboxRuntimeError = type("SandboxRuntimeError", (Exception,), {})
        with patch(
            "app.tasks.execution_tasks.os.path.isfile", return_value=True
        ), patch("app.tasks.execution_tasks.os.makedirs"), patch.dict(
            os.environ, {"ENABLE_SANDBOX": "true"}
        ), patch("app.tasks.execution_tasks.subprocess.run"), patch(
            "app.executions.services.parse_pytest_output"
        ), patch.dict("sys.modules", {"app.tasks.sandbox": mock_sandbox}):
            result = stage_run_tests(execution.id)
        assert result == execution.id
        mock_runner.run.assert_called_once()


# ===================================================================
# stage_generate_report tests
# ===================================================================


class TestStageGenerateReport:
    def test_generate_report_success(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_generate_report
        from app.extensions import db as _db

        execution.status = ExecutionStatus.EXECUTED
        _db.session.commit()
        with patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.shutil.rmtree"), patch(
            "app.tasks.execution_tasks._cleanup_venv"
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = stage_generate_report(execution.id)
        _db.session.refresh(execution)
        assert result == execution.id
        assert execution.status == ExecutionStatus.COMPLETED

    def test_generate_report_allure_failure(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_generate_report, PipelineAbort
        from app.extensions import db as _db

        execution.status = ExecutionStatus.EXECUTED
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "allure", stderr="allure not found"
            ),
        ), patch("app.tasks.execution_tasks.os.path.isdir", return_value=False), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ), patch("app.tasks.execution_tasks._cleanup_venv"):
            with pytest.raises(PipelineAbort):
                stage_generate_report(execution.id)

    def test_generate_report_timeout(self, mock_redis, execution, sample_project, app):
        from app.tasks.execution_tasks import stage_generate_report, PipelineAbort
        from app.extensions import db as _db

        execution.status = ExecutionStatus.EXECUTED
        _db.session.commit()
        with patch(
            "app.tasks.execution_tasks.subprocess.run",
            side_effect=subprocess.TimeoutExpired("allure", 300),
        ), patch("app.tasks.execution_tasks.os.path.isdir", return_value=False), patch(
            "app.tasks.execution_tasks.shutil.rmtree"
        ), patch("app.tasks.execution_tasks._cleanup_venv"):
            with pytest.raises(PipelineAbort):
                stage_generate_report(execution.id)

    def test_generate_report_cleans_venv(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_generate_report
        from app.extensions import db as _db

        execution.status = ExecutionStatus.EXECUTED
        _db.session.commit()
        with patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.shutil.rmtree"), patch(
            "app.tasks.execution_tasks._cleanup_venv"
        ) as mock_cleanup:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            stage_generate_report(execution.id)
        mock_cleanup.assert_called()

    def test_generate_report_creates_allure_record(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_generate_report
        from app.models.allure_report import AllureReport
        from app.extensions import db as _db

        execution.status = ExecutionStatus.EXECUTED
        _db.session.commit()
        with patch("app.tasks.execution_tasks.subprocess.run") as mock_run, patch(
            "app.tasks.execution_tasks.os.path.isdir", return_value=False
        ), patch("app.tasks.execution_tasks.shutil.rmtree"), patch(
            "app.tasks.execution_tasks._cleanup_venv"
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            stage_generate_report(execution.id)
        report = AllureReport.query.filter_by(execution_id=execution.id).first()
        assert report is not None
        assert report.execution_id == execution.id

    def test_generate_report_already_terminal(
        self, mock_redis, execution, sample_project, app
    ):
        from app.tasks.execution_tasks import stage_generate_report
        from app.extensions import db as _db

        execution.status = ExecutionStatus.FAILED
        _db.session.commit()
        result = stage_generate_report(execution.id)
        assert result == execution.id
        assert execution.status == ExecutionStatus.FAILED


# ===================================================================
# Helper tests
# ===================================================================


class TestHelpers:
    def test_set_status(self, mock_redis, execution):
        from app.tasks.execution_tasks import _set_status

        _set_status(execution, ExecutionStatus.RUNNING)
        assert execution.status == ExecutionStatus.RUNNING

    def test_fail_execution_raises_pipeline_abort(self, mock_redis, execution):
        from app.tasks.execution_tasks import _fail_execution, PipelineAbort

        with pytest.raises(PipelineAbort):
            _fail_execution(execution, "something broke")
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_detail == "something broke"
        assert execution.finished_at is not None

    def test_timeout_execution_raises_pipeline_abort(self, mock_redis, execution):
        from app.tasks.execution_tasks import _timeout_execution, PipelineAbort

        with pytest.raises(PipelineAbort):
            _timeout_execution(execution)
        assert execution.status == ExecutionStatus.TIMEOUT

    def test_cleanup_venv_nonexistent(self):
        from app.tasks.execution_tasks import _cleanup_venv

        with patch("app.tasks.execution_tasks.os.path.isdir", return_value=False):
            _cleanup_venv("/nonexistent/venv")

    def test_cleanup_venv_removes_existing(self, tmp_path):
        from app.tasks.execution_tasks import _cleanup_venv

        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "placeholder.txt").write_text("x")
        with patch("app.tasks.execution_tasks.shutil.rmtree") as mock_rm:
            _cleanup_venv(str(venv_dir))
        mock_rm.assert_called_once_with(str(venv_dir))

    def test_build_clone_url_delegates(self):
        from app.tasks.execution_tasks import _build_clone_url

        result = _build_clone_url("https://github.com/example/repo.git", "token123")
        assert result == "https://token123@github.com/example/repo.git"

    def test_build_clone_url_no_credential(self):
        from app.tasks.execution_tasks import _build_clone_url

        result = _build_clone_url("https://github.com/example/repo.git", None)
        assert result == "https://github.com/example/repo.git"

    def test_terminate_execution_releases_slot(self, mock_redis, execution):
        from app.tasks.execution_tasks import _terminate_execution, PipelineAbort

        with pytest.raises(PipelineAbort):
            _terminate_execution(execution, ExecutionStatus.FAILED, "err")
        mock_redis.srem.assert_called()
        mock_redis.delete.assert_called()

    def test_terminate_execution_with_venv_cleanup(self, mock_redis, execution):
        from app.tasks.execution_tasks import _terminate_execution, PipelineAbort

        with patch("app.tasks.execution_tasks._cleanup_venv") as mock_clean:
            with pytest.raises(PipelineAbort):
                _terminate_execution(
                    execution, ExecutionStatus.FAILED, "err", cleanup_venv="/tmp/venv"
                )
            mock_clean.assert_called_once_with("/tmp/venv")

    def test_acquire_slot_exception_returns_false(self, mock_redis):
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_redis.pipeline.return_value.watch.side_effect = ConnectionError(
            "redis down"
        )
        assert _acquire_exec_slot(1) is False

    def test_recover_stale_slots_exception(self, mock_redis):
        from app.tasks.execution_tasks import _recover_stale_slots

        mock_redis.smembers.side_effect = ConnectionError("redis down")
        # Should not raise -- exception is caught internally
        _recover_stale_slots()

    def test_get_max_slots_non_int_value(self, app):
        from app.models.system_config import SystemConfig
        from app.extensions import db as _db

        cfg = SystemConfig(key="max_exec_slots", value="not_a_number", value_type="int")
        _db.session.add(cfg)
        _db.session.commit()
        from app.tasks.execution_tasks import _get_max_slots

        # int("not_a_number") raises ValueError but it's caught by except Exception
        # so it falls through to the default
        assert _get_max_slots() == 3
