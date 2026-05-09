"""Cron schedule task tests."""

from unittest.mock import MagicMock, patch
import pytest


class TestRunCronSchedule:
    @patch("app.tasks.schedule_tasks.db")
    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    @patch("app.executions.services.prepare_execution")
    def test_success_dispatches_pipeline(self, mock_prepare, mock_pipeline, mock_db):
        """Active schedule creates execution and dispatches pipeline."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = True
        mock_schedule.project_id = 1
        mock_schedule.suite_id = None
        mock_schedule.last_run = None
        mock_db.session.get.return_value = mock_schedule

        mock_execution = MagicMock()
        mock_execution.id = 42
        mock_prepare.return_value = mock_execution

        run_cron_schedule.run(schedule_id=1)

        mock_prepare.assert_called_once()
        mock_pipeline.delay.assert_called_once_with(42)

    @patch("app.tasks.schedule_tasks.db")
    def test_inactive_schedule_skipped(self, mock_db):
        """Inactive schedule returns early."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = False
        mock_db.session.get.return_value = mock_schedule

        run_cron_schedule.run(schedule_id=1)
        # No exception means it returned early

    @patch("app.tasks.schedule_tasks.db")
    def test_missing_schedule_skipped(self, mock_db):
        """Non-existent schedule returns early."""
        from app.tasks.schedule_tasks import run_cron_schedule
        mock_db.session.get.return_value = None
        run_cron_schedule.run(schedule_id=999)

    @patch("app.tasks.schedule_tasks.db")
    @patch("app.executions.services.prepare_execution", side_effect=Exception("db error"))
    def test_exception_triggers_rollback(self, mock_prepare, mock_db):
        """Exception in prepare_execution triggers rollback."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = True
        mock_db.session.get.return_value = mock_schedule

        with pytest.raises(Exception):
            run_cron_schedule.run(schedule_id=1)
        mock_db.session.rollback.assert_called()


class TestCronScheduleModel:
    def test_model_has_required_fields(self):
        """CronSchedule model has expected columns."""
        from app.models.cron_schedule import CronSchedule
        assert hasattr(CronSchedule, 'project_id')
        assert hasattr(CronSchedule, 'cron_expr')
        assert hasattr(CronSchedule, 'is_active')
