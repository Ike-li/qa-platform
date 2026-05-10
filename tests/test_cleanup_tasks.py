"""Tests for app.tasks.cleanup_tasks – enforce_retention Celery task."""

from unittest.mock import MagicMock, patch

import pytest


class TestEnforceRetention:
    """Tests for the enforce_retention Celery task."""

    def test_success_delegates_to_admin(self):
        """On success, returns the result dict from admin service."""
        from app.tasks.cleanup_tasks import enforce_retention

        mock_result = {
            "executions_deleted": 12,
            "reports_deleted": 7,
            "audit_deleted": 4,
        }
        with patch("app.admin.services.enforce_retention", return_value=mock_result):
            result = enforce_retention.run()
            assert result == mock_result

    def test_success_logs_counts(self, caplog):
        """On success, logs the deletion counts."""
        import logging

        from app.tasks.cleanup_tasks import enforce_retention

        mock_result = {
            "executions_deleted": 1,
            "reports_deleted": 2,
            "audit_deleted": 3,
        }
        with caplog.at_level(logging.INFO, logger="app.tasks.cleanup_tasks"):
            with patch(
                "app.admin.services.enforce_retention", return_value=mock_result
            ):
                enforce_retention.run()
        assert "executions=1" in caplog.text
        assert "reports=2" in caplog.text
        assert "audit=3" in caplog.text

    def test_exception_retries(self):
        """When admin service raises, task retries via self.retry."""
        from celery.exceptions import Retry

        from app.tasks.cleanup_tasks import enforce_retention

        with patch(
            "app.admin.services.enforce_retention",
            side_effect=RuntimeError("db failure"),
        ):
            # Replace retry so it raises Retry (Celery's expected behavior)
            original_retry = enforce_retention.retry
            enforce_retention.retry = MagicMock(side_effect=Retry())
            try:
                with pytest.raises(Retry):
                    enforce_retention.run()
                enforce_retention.retry.assert_called_once()
            finally:
                enforce_retention.retry = original_retry
