"""Unit tests for execution_tasks.py helper functions.

Covers: _get_max_slots, _acquire_exec_slot, _release_exec_slot,
_recover_stale_slots, _set_status, _terminate_execution, _fail_execution,
_timeout_execution, _cleanup_venv, and run_execution_pipeline.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.execution import ExecutionStatus


class TestGetMaxSlots:
    """Tests for _get_max_slots."""

    @patch("app.models.system_config.SystemConfig")
    def test_returns_configured_value(self, mock_sysconfig):
        """Returns value from SystemConfig.get when available."""
        from app.tasks.execution_tasks import _get_max_slots

        mock_sysconfig.get.return_value = 5
        assert _get_max_slots() == 5
        mock_sysconfig.get.assert_called_once_with("max_exec_slots")

    @patch("app.models.system_config.SystemConfig")
    def test_returns_default_when_exception(self, mock_sysconfig):
        """Returns DEFAULT_MAX_EXEC_SLOTS when SystemConfig.get raises."""
        from app.tasks.execution_tasks import _get_max_slots, DEFAULT_MAX_EXEC_SLOTS

        mock_sysconfig.get.side_effect = RuntimeError("db unavailable")
        assert _get_max_slots() == DEFAULT_MAX_EXEC_SLOTS

    @patch("app.models.system_config.SystemConfig")
    def test_returns_default_when_none(self, mock_sysconfig):
        """Returns DEFAULT_MAX_EXEC_SLOTS when SystemConfig.get returns None."""
        from app.tasks.execution_tasks import _get_max_slots, DEFAULT_MAX_EXEC_SLOTS

        mock_sysconfig.get.return_value = None
        assert _get_max_slots() == DEFAULT_MAX_EXEC_SLOTS


class TestAcquireExecSlot:
    """Tests for _acquire_exec_slot."""

    @patch("app.tasks.execution_tasks._get_max_slots", return_value=3)
    @patch("app.tasks.execution_tasks._redis")
    def test_returns_true_when_slot_available(self, mock_redis, mock_max):
        """Returns True when active slots < max."""
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_redis.scard.return_value = 1  # 1 active < 3 max

        result = _acquire_exec_slot(42)

        assert result is True
        mock_pipe.watch.assert_called_once()
        mock_pipe.multi.assert_called_once()
        mock_pipe.execute.assert_called_once()

    @patch("app.tasks.execution_tasks._get_max_slots", return_value=3)
    @patch("app.tasks.execution_tasks._redis")
    def test_returns_false_when_full(self, mock_redis, mock_max):
        """Returns False when active slots >= max."""
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_redis.scard.return_value = 3  # 3 active >= 3 max

        result = _acquire_exec_slot(42)

        assert result is False
        mock_pipe.reset.assert_called_once()
        mock_pipe.multi.assert_not_called()

    @patch(
        "app.tasks.execution_tasks._get_max_slots", side_effect=Exception("redis down")
    )
    @patch("app.tasks.execution_tasks._redis")
    def test_returns_false_on_exception(self, mock_redis, mock_max):
        """Returns False when Redis raises exception."""
        from app.tasks.execution_tasks import _acquire_exec_slot

        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.watch.side_effect = Exception("redis down")

        result = _acquire_exec_slot(42)

        assert result is False


class TestReleaseExecSlot:
    """Tests for _release_exec_slot."""

    @patch("app.tasks.execution_tasks._redis")
    def test_calls_srem_and_delete(self, mock_redis):
        """Releases slot by calling srem and delete on _redis."""
        from app.tasks.execution_tasks import _release_exec_slot

        _release_exec_slot(42)

        mock_redis.srem.assert_called_once_with("exec_slots", "42")
        mock_redis.delete.assert_called_once_with("exec_slot_ttl:42")

    @patch("app.tasks.execution_tasks._redis", side_effect=Exception("redis down"))
    def test_catches_exception(self, mock_redis):
        """Catches and logs warning when Redis raises."""
        from app.tasks.execution_tasks import _release_exec_slot

        # Should not raise
        _release_exec_slot(42)


class TestRecoverStaleSlots:
    """Tests for _recover_stale_slots."""

    @patch("app.tasks.execution_tasks._redis")
    def test_removes_stale_members(self, mock_redis):
        """Removes members whose TTL key has expired."""
        from app.tasks.execution_tasks import _recover_stale_slots, EXEC_SLOT_SET

        mock_redis.smembers.return_value = {b"1", b"2"}
        # TTL key for '1' is expired, for '2' is still alive
        mock_redis.exists.side_effect = lambda key: key != "exec_slot_ttl:1"

        _recover_stale_slots()

        mock_redis.srem.assert_called_once_with(EXEC_SLOT_SET, b"1")

    @patch("app.tasks.execution_tasks._redis")
    def test_empty_set_noop(self, mock_redis):
        """No-op when set is empty."""
        from app.tasks.execution_tasks import _recover_stale_slots

        mock_redis.smembers.return_value = set()

        _recover_stale_slots()

        mock_redis.srem.assert_not_called()

    @patch("app.tasks.execution_tasks._redis")
    def test_catches_redis_exception(self, mock_redis):
        """Catches and logs warning on Redis exception."""
        from app.tasks.execution_tasks import _recover_stale_slots

        mock_redis.smembers.side_effect = Exception("redis down")

        # Should not raise
        _recover_stale_slots()


class TestSetStatus:
    """Tests for _set_status."""

    @patch("app.tasks.execution_tasks.db")
    def test_sets_status_and_commits(self, mock_db):
        """Sets execution.status and commits."""
        from app.tasks.execution_tasks import _set_status

        execution = MagicMock()
        execution.id = 42

        _set_status(execution, ExecutionStatus.RUNNING)

        assert execution.status == ExecutionStatus.RUNNING
        mock_db.session.commit.assert_called_once()


class TestTerminateExecution:
    """Tests for _terminate_execution."""

    @patch("app.tasks.execution_tasks._cleanup_venv")
    @patch("app.tasks.execution_tasks._release_exec_slot")
    @patch("app.tasks.execution_tasks.db")
    def test_raises_pipeline_abort(self, mock_db, mock_release, mock_cleanup):
        """Sets status, commits, releases slot, and raises PipelineAbort."""
        from app.tasks.execution_tasks import _terminate_execution, PipelineAbort

        execution = MagicMock()
        execution.id = 42

        with pytest.raises(PipelineAbort):
            _terminate_execution(execution, ExecutionStatus.FAILED, "test error")

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_detail == "test error"
        assert execution.finished_at is not None
        execution.update_duration.assert_called_once()
        mock_db.session.commit.assert_called_once()
        mock_release.assert_called_once_with(42)
        mock_cleanup.assert_not_called()

    @patch("app.tasks.execution_tasks._cleanup_venv")
    @patch("app.tasks.execution_tasks._release_exec_slot")
    @patch("app.tasks.execution_tasks.db")
    def test_cleanup_venv_when_path_provided(self, mock_db, mock_release, mock_cleanup):
        """Calls _cleanup_venv when cleanup_venv path is provided."""
        from app.tasks.execution_tasks import _terminate_execution, PipelineAbort

        execution = MagicMock()
        execution.id = 42

        with pytest.raises(PipelineAbort):
            _terminate_execution(
                execution, ExecutionStatus.FAILED, "error", cleanup_venv="/tmp/venv"
            )

        mock_cleanup.assert_called_once_with("/tmp/venv")


class TestFailExecution:
    """Tests for _fail_execution."""

    @patch("app.tasks.execution_tasks._terminate_execution")
    def test_delegates_to_terminate(self, mock_terminate):
        """Delegates to _terminate_execution with FAILED status."""
        from app.tasks.execution_tasks import _fail_execution

        execution = MagicMock()

        _fail_execution(execution, "some error", cleanup_venv="/tmp/v")

        mock_terminate.assert_called_once_with(
            execution, ExecutionStatus.FAILED, "some error", "/tmp/v"
        )


class TestTimeoutExecution:
    """Tests for _timeout_execution."""

    @patch("app.tasks.execution_tasks._terminate_execution")
    def test_delegates_to_terminate(self, mock_terminate):
        """Delegates to _terminate_execution with TIMEOUT status."""
        from app.tasks.execution_tasks import _timeout_execution

        execution = MagicMock()

        _timeout_execution(execution, cleanup_venv="/tmp/v")

        mock_terminate.assert_called_once_with(
            execution, ExecutionStatus.TIMEOUT, "Execution timed out.", "/tmp/v"
        )


class TestCleanupVenv:
    """Tests for _cleanup_venv."""

    @patch("app.tasks.execution_tasks.shutil.rmtree")
    @patch("app.tasks.execution_tasks.os.path.isdir", return_value=True)
    def test_removes_directory(self, mock_isdir, mock_rmtree):
        """Removes directory when isdir is True."""
        from app.tasks.execution_tasks import _cleanup_venv

        _cleanup_venv("/tmp/venv")

        mock_rmtree.assert_called_once_with("/tmp/venv")

    @patch(
        "app.tasks.execution_tasks.shutil.rmtree", side_effect=OSError("perm denied")
    )
    @patch("app.tasks.execution_tasks.os.path.isdir", return_value=True)
    def test_handles_oserror(self, mock_isdir, mock_rmtree):
        """Handles OSError from rmtree gracefully."""
        from app.tasks.execution_tasks import _cleanup_venv

        # Should not raise
        _cleanup_venv("/tmp/venv")

    @patch("app.tasks.execution_tasks.shutil.rmtree")
    @patch("app.tasks.execution_tasks.os.path.isdir", return_value=False)
    def test_noop_when_not_directory(self, mock_isdir, mock_rmtree):
        """No-op when path is not a directory."""
        from app.tasks.execution_tasks import _cleanup_venv

        _cleanup_venv("/tmp/venv")

        mock_rmtree.assert_not_called()


class TestRunExecutionPipeline:
    """Tests for run_execution_pipeline."""

    @patch("app.tasks.execution_tasks.stage_generate_report")
    @patch("app.tasks.execution_tasks.stage_run_tests")
    @patch("app.tasks.execution_tasks.stage_git_sync")
    @patch("app.tasks.execution_tasks.chain")
    @patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=True)
    def test_slot_acquired_dispatches_chain(
        self, mock_acquire, mock_chain, mock_s1, mock_s2, mock_s3
    ):
        """When slot acquired, dispatches 3-stage chain and returns execution_id."""
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_pipeline = MagicMock()
        mock_chain.return_value = mock_pipeline

        result = run_execution_pipeline.run(42)

        assert result == 42
        mock_acquire.assert_called_once_with(42)
        mock_pipeline.apply_async.assert_called_once()

    @patch("app.tasks.execution_tasks._fail_execution")
    @patch("app.tasks.execution_tasks.db")
    @patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=False)
    def test_slot_not_acquired_fails_execution(self, mock_acquire, mock_db, mock_fail):
        """When slot not acquired and execution exists, fails it."""
        from app.tasks.execution_tasks import run_execution_pipeline

        mock_execution = MagicMock()
        mock_db.session.get.return_value = mock_execution

        # _fail_execution raises PipelineAbort internally
        from app.tasks.execution_tasks import PipelineAbort

        mock_fail.side_effect = PipelineAbort("no slots")

        result = run_execution_pipeline.run(42)

        assert result == 42

    @patch("app.tasks.execution_tasks._fail_execution")
    @patch("app.tasks.execution_tasks.db")
    @patch("app.tasks.execution_tasks._acquire_exec_slot", return_value=False)
    def test_pipeline_abort_returns_gracefully(self, mock_acquire, mock_db, mock_fail):
        """When PipelineAbort raised during fail, returns execution_id gracefully."""
        from app.tasks.execution_tasks import run_execution_pipeline, PipelineAbort

        mock_execution = MagicMock()
        mock_db.session.get.return_value = mock_execution
        mock_fail.side_effect = PipelineAbort("no slots")

        result = run_execution_pipeline.run(99)

        assert result == 99
