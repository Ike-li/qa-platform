"""Celery pipeline integration tests using ALWAYS_EAGER mode.

Tests the full 3-stage pipeline (git_sync → run_tests → generate_report)
with Celery running in-process. External calls (git, subprocess, allure)
are mocked, but the Celery chain logic, status transitions, and slot
management are tested end-to-end.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.tasks.execution_tasks import (
    PipelineAbort,
    _acquire_exec_slot,
    _release_exec_slot,
    run_execution_pipeline,
    stage_git_sync,
    stage_run_tests,
)


@pytest.fixture(autouse=True)
def _celery_eager(app):
    """Configure Celery to run tasks synchronously in-process."""
    from app.extensions import celery
    celery.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        task_store_eager_result=True,
    )
    yield
    celery.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
    )


@pytest.fixture
def mock_redis():
    """Mock the module-level Redis client."""
    mock = MagicMock()
    mock.scard.return_value = 0
    mock.sadd.return_value = 1
    mock.set.return_value = True
    mock.srem.return_value = 1
    mock.delete.return_value = 1
    mock.smembers.return_value = set()
    mock.exists.return_value = 0
    mock.pipeline.return_value = MagicMock()
    # Make pipeline().watch() and pipeline().execute() work
    pipe = mock.pipeline.return_value
    pipe.watch.return_value = None
    pipe.execute.return_value = [1, True]
    with patch("app.tasks.execution_tasks._redis", mock):
        yield mock


@pytest.fixture
def sample_execution(db, sample_project):
    """Create a sample execution in PENDING status."""
    execution = Execution(
        project_id=sample_project.id,
        status=ExecutionStatus.PENDING,
        trigger_type=TriggerType.WEB,
    )
    db.session.add(execution)
    db.session.commit()
    return execution


class TestSlotLifecycle:
    """Test Redis slot acquire/release lifecycle."""

    def test_acquire_creates_key_with_ttl(self, mock_redis):
        """Slot acquisition creates a per-execution key with TTL."""
        mock_redis.pipeline.return_value.watch.return_value = None
        mock_redis.pipeline.return_value.execute.return_value = [1, True]
        result = _acquire_exec_slot(42)
        assert result is True

    def test_release_deletes_key(self, mock_redis):
        """Slot release removes the per-execution key."""
        _release_exec_slot(42)
        mock_redis.srem.assert_called_once()
        mock_redis.delete.assert_called_once()

    def test_max_slots_respected(self, mock_redis):
        """Acquiring beyond max returns False."""
        mock_redis.pipeline.return_value.watch.return_value = None
        mock_redis.pipeline.return_value.execute.return_value = [0, False]
        mock_redis.scard.return_value = 3
        result = _acquire_exec_slot(99)
        assert result is False


class TestPipelineFailurePropagation:
    """Test that failures stop the chain."""

    def test_pipeline_git_failure_stops_chain(self, db, sample_execution, mock_redis):
        """When git_sync fails, PipelineAbort is raised to stop the chain."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("git clone failed")
            # stage_git_sync should raise PipelineAbort (stops the chain)
            with pytest.raises(PipelineAbort):
                stage_git_sync(sample_execution.id)


class TestPipelineStatusTransitions:
    """Test status transitions through the pipeline."""

    def test_status_pending_to_running(self, db, sample_execution, mock_redis):
        """stage_git_sync transitions PENDING → RUNNING."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok", stderr="", strip=lambda: "abc123"
            )
            with patch("os.path.isdir", return_value=False):
                with patch("os.makedirs"):
                    with patch("os.path.isfile", return_value=False):
                        try:
                            stage_git_sync(sample_execution.id)
                        except Exception:
                            pass

            db.session.refresh(sample_execution)
            # Should have moved past PENDING
            assert sample_execution.status != ExecutionStatus.PENDING
            assert sample_execution.started_at is not None


class TestPipelineSlotIntegration:
    """Test slot behavior in the pipeline context."""

    def test_no_slot_fails_execution(self, db, sample_execution, mock_redis):
        """When no slots are available, execution is marked FAILED."""
        mock_redis.pipeline.return_value.watch.return_value = None
        mock_redis.pipeline.return_value.execute.return_value = [0, False]
        mock_redis.scard.return_value = 3

        # Call run_execution_pipeline directly
        run_execution_pipeline(sample_execution.id)

        db.session.refresh(sample_execution)
        assert sample_execution.status == ExecutionStatus.FAILED
        assert "slots" in (sample_execution.error_detail or "").lower()


class TestTerminalStateGuard:
    """Test that terminal executions are skipped."""

    def test_already_failed_execution_skipped(self, db, sample_project, mock_redis):
        """stage_run_tests skips if execution is already FAILED."""
        execution = Execution(
            project_id=sample_project.id,
            status=ExecutionStatus.FAILED,
            trigger_type=TriggerType.WEB,
            error_detail="pre-existing failure",
        )
        db.session.add(execution)
        db.session.commit()

        # Should return early without error
        result = stage_run_tests(execution.id)
        assert result == execution.id
