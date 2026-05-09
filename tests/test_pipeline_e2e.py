"""End-to-end pipeline tests with Celery ALWAYS_EAGER."""

from unittest.mock import MagicMock, patch
import pytest
from app.tasks.execution_tasks import (
    PipelineAbort, stage_git_sync, stage_run_tests, stage_generate_report,
    _acquire_exec_slot, _release_exec_slot,
)
from app.models.execution import Execution, ExecutionStatus, TriggerType


@pytest.fixture(autouse=True)
def _celery_eager(app):
    from app.extensions import celery
    celery.conf.update(task_always_eager=True, task_eager_propagates=True, task_store_eager_result=True)
    yield
    celery.conf.update(task_always_eager=False, task_eager_propagates=False)


@pytest.fixture
def mock_redis():
    mock = MagicMock()
    mock.scard.return_value = 0
    mock.sadd.return_value = 1
    mock.set.return_value = True
    mock.srem.return_value = 1
    mock.delete.return_value = 1
    mock.smembers.return_value = set()
    mock.exists.return_value = 0
    pipe = MagicMock()
    mock.pipeline.return_value = pipe
    pipe.watch.return_value = None
    pipe.execute.return_value = [1, True]
    with patch("app.tasks.execution_tasks._redis", mock):
        yield mock


@pytest.fixture
def sample_execution(db, sample_project):
    execution = Execution(project_id=sample_project.id, status=ExecutionStatus.PENDING, trigger_type=TriggerType.WEB)
    db.session.add(execution)
    db.session.commit()
    return execution


class TestSlotLifecycle:
    def test_acquire_creates_slot(self, mock_redis):
        result = _acquire_exec_slot(42)
        assert result is True

    def test_release_deletes_slot(self, mock_redis):
        _release_exec_slot(42)
        mock_redis.srem.assert_called_once()

    def test_max_slots_blocks(self, mock_redis):
        mock_redis.pipeline.return_value.watch.return_value = None
        mock_redis.pipeline.return_value.execute.return_value = [0, False]
        mock_redis.scard.return_value = 3
        assert _acquire_exec_slot(99) is False


class TestPipelineFailure:
    def test_git_failure_raises_pipeline_abort(self, db, sample_execution, mock_redis):
        with patch("subprocess.run", side_effect=Exception("git failed")):
            with pytest.raises(PipelineAbort):
                stage_git_sync(sample_execution.id)


class TestTerminalGuard:
    def test_already_failed_skipped(self, db, sample_project, mock_redis):
        execution = Execution(project_id=sample_project.id, status=ExecutionStatus.FAILED, trigger_type=TriggerType.WEB, error_detail="pre-existing")
        db.session.add(execution)
        db.session.commit()
        result = stage_run_tests(execution.id)
        assert result == execution.id


class TestStatusTransitions:
    def test_git_sync_sets_started_at(self, db, sample_execution, mock_redis):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="", strip=lambda: "abc123")
            with patch("os.path.isdir", return_value=False), patch("os.makedirs"), patch("os.path.isfile", return_value=False):
                try:
                    stage_git_sync(sample_execution.id)
                except Exception:
                    pass
        db.session.refresh(sample_execution)
        assert sample_execution.status != ExecutionStatus.PENDING
        assert sample_execution.started_at is not None
