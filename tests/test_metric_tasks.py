"""Tests for app.tasks.metric_tasks – aggregate_all_metrics Celery task."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch


class TestAggregateAllMetrics:
    """Tests for the aggregate_all_metrics Celery task."""

    @patch("app.tasks.metric_tasks.db")
    @patch("app.tasks.metric_tasks.Project")
    def test_no_projects_skips(self, mock_project_cls, mock_db):
        """When no projects exist, task returns early."""
        from app.tasks.metric_tasks import aggregate_all_metrics

        mock_project_cls.query.all.return_value = []
        result = aggregate_all_metrics()
        assert result is None

    @patch("app.tasks.metric_tasks.db")
    @patch("app.tasks.metric_tasks.aggregate_daily_metrics")
    @patch("app.tasks.metric_tasks.Project")
    def test_aggregates_yesterday(self, mock_project_cls, mock_agg, mock_db):
        """Calls aggregate_daily_metrics for each project with yesterday's date."""
        from app.tasks.metric_tasks import aggregate_all_metrics

        p1 = MagicMock()
        p1.id = 1
        p2 = MagicMock()
        p2.id = 2
        mock_project_cls.query.all.return_value = [p1, p2]

        aggregate_all_metrics()

        expected_date = date.today() - timedelta(days=1)
        assert mock_agg.call_count == 2
        mock_agg.assert_any_call(1, expected_date)
        mock_agg.assert_any_call(2, expected_date)

    @patch("app.tasks.metric_tasks.db")
    @patch("app.tasks.metric_tasks.aggregate_daily_metrics")
    @patch("app.tasks.metric_tasks.Project")
    def test_rollback_on_failure(self, mock_project_cls, mock_agg, mock_db):
        """Failed aggregation for one project triggers rollback but continues."""
        from app.tasks.metric_tasks import aggregate_all_metrics

        p1 = MagicMock()
        p1.id = 1
        p2 = MagicMock()
        p2.id = 2
        mock_project_cls.query.all.return_value = [p1, p2]

        mock_agg.side_effect = [RuntimeError("db error"), None]

        aggregate_all_metrics()

        mock_db.session.rollback.assert_called_once()
        assert mock_agg.call_count == 2

    @patch("app.tasks.metric_tasks.db")
    @patch("app.tasks.metric_tasks.aggregate_daily_metrics")
    @patch("app.tasks.metric_tasks.Project")
    def test_all_failures_still_completes(self, mock_project_cls, mock_agg, mock_db):
        """Even if all projects fail, task completes without raising."""
        from app.tasks.metric_tasks import aggregate_all_metrics

        p1 = MagicMock()
        p1.id = 1
        mock_project_cls.query.all.return_value = [p1]
        mock_agg.side_effect = RuntimeError("boom")

        # Should not raise
        aggregate_all_metrics()
        assert mock_db.session.rollback.call_count == 1
