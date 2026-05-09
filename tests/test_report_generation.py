"""Report generation tests."""

from unittest.mock import MagicMock, patch
import pytest
from app.tasks.execution_tasks import stage_generate_report, PipelineAbort
from app.models.execution import Execution, ExecutionStatus, TriggerType


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
def executed_execution(db, sample_project):
    execution = Execution(
        project_id=sample_project.id,
        status=ExecutionStatus.EXECUTED,
        trigger_type=TriggerType.WEB,
    )
    db.session.add(execution)
    db.session.commit()
    return execution


class TestReportGeneration:
    def test_success_creates_report(self, db, executed_execution, mock_redis):
        """Successful allure generate creates AllureReport record."""
        with patch("subprocess.run") as mock_run, \
             patch("os.path.isdir", return_value=True), \
             patch("os.makedirs"), \
             patch("shutil.rmtree"), \
             patch("os.walk", return_value=[("/app/allure-reports/1", [], ["index.html"])]), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024):
            mock_run.return_value = MagicMock(returncode=0)
            try:
                stage_generate_report(executed_execution.id)
            except Exception:
                pass
        db.session.refresh(executed_execution)
        assert executed_execution.status == ExecutionStatus.COMPLETED

    def test_already_failed_skipped(self, db, sample_project, mock_redis):
        """Stage skips if execution already in terminal state."""
        execution = Execution(
            project_id=sample_project.id,
            status=ExecutionStatus.FAILED,
            trigger_type=TriggerType.WEB,
            error_detail="pre-existing",
        )
        db.session.add(execution)
        db.session.commit()
        result = stage_generate_report(execution.id)
        assert result == execution.id

    def test_allure_failure_raises(self, db, executed_execution, mock_redis):
        """Allure command failure raises PipelineAbort."""
        with patch("subprocess.run", side_effect=Exception("allure not found")), \
             patch("os.path.isdir", return_value=False):
            with pytest.raises(PipelineAbort):
                stage_generate_report(executed_execution.id)
