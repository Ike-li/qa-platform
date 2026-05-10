"""Additional tests for app.tasks.schedule_tasks – supplementary coverage.

The core run_cron_schedule paths (success, inactive, missing, rollback) are
already covered in tests/test_cron_schedule.py.  This file adds tests for
the last_run timestamp update and edge cases.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestRunCronScheduleDetail:
    """Supplementary tests for run_cron_schedule task."""

    @patch("app.tasks.schedule_tasks.db")
    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    @patch("app.executions.services.prepare_execution")
    def test_last_run_updated_on_success(self, mock_prepare, mock_pipeline, mock_db):
        """schedule.last_run is set to current UTC time after dispatch."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = True
        mock_schedule.project_id = 1
        mock_schedule.suite_id = 5
        mock_schedule.last_run = None
        mock_db.session.get.return_value = mock_schedule

        mock_exec = MagicMock()
        mock_exec.id = 42
        mock_prepare.return_value = mock_exec

        run_cron_schedule.run(schedule_id=1)

        assert mock_schedule.last_run is not None
        mock_db.session.commit.assert_called_once()

    @patch("app.tasks.schedule_tasks.db")
    @patch("app.tasks.execution_tasks.run_execution_pipeline")
    @patch("app.executions.services.prepare_execution")
    def test_dispatches_pipeline_with_execution_id(
        self, mock_prepare, mock_pipeline, mock_db
    ):
        """Pipeline is dispatched with the created execution's id."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = True
        mock_schedule.project_id = 2
        mock_schedule.suite_id = None
        mock_db.session.get.return_value = mock_schedule

        mock_exec = MagicMock()
        mock_exec.id = 99
        mock_prepare.return_value = mock_exec

        run_cron_schedule.run(schedule_id=7)

        mock_pipeline.delay.assert_called_once_with(99)
        mock_prepare.assert_called_once_with(
            project_id=2,
            suite_id=None,
            trigger_type=mock_prepare.call_args.kwargs["trigger_type"],
        )

    @patch("app.tasks.schedule_tasks.db")
    @patch(
        "app.executions.services.prepare_execution",
        side_effect=Exception("pipeline err"),
    )
    def test_exception_does_not_commit(self, mock_prepare, mock_db):
        """On exception, commit is NOT called (rollback happens instead)."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = True
        mock_db.session.get.return_value = mock_schedule

        with pytest.raises(Exception):
            run_cron_schedule.run(schedule_id=1)

        mock_db.session.rollback.assert_called()
        mock_db.session.commit.assert_not_called()

    @patch("app.tasks.schedule_tasks.db")
    def test_inactive_does_not_prepare(self, mock_db):
        """Inactive schedule never calls prepare_execution."""
        from app.tasks.schedule_tasks import run_cron_schedule

        mock_schedule = MagicMock()
        mock_schedule.is_active = False
        mock_db.session.get.return_value = mock_schedule

        with patch("app.executions.services.prepare_execution") as mock_prepare:
            run_cron_schedule.run(schedule_id=1)
            mock_prepare.assert_not_called()
