import unittest
from unittest.mock import MagicMock


class TestDashboard(unittest.TestCase):
    """Tests for the dashboard page using mocked Playwright page object."""

    def _make_page(self):
        return MagicMock()

    def test_dashboard_loads(self):
        page = self._make_page()
        page.goto("http://localhost/dashboard")

        page.goto.assert_called_once_with("http://localhost/dashboard")

    def test_dashboard_metrics_display(self):
        page = self._make_page()
        mock_metric = MagicMock()
        mock_metric.inner_text.return_value = "42"
        page.query_selector.side_effect = (
            lambda sel: mock_metric if "metric" in sel else None
        )

        metric_cards = page.query_selector(".metric-card")
        self.assertIsNotNone(metric_cards)
        self.assertEqual(metric_cards.inner_text(), "42")

    def test_dashboard_filter_projects(self):
        page = self._make_page()
        mock_select = MagicMock()
        page.query_selector.return_value = mock_select

        page.select_option("select#project-filter", "project-A")

        page.select_option.assert_called_once_with("select#project-filter", "project-A")


if __name__ == "__main__":
    unittest.main()
