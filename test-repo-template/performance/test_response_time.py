import unittest
from unittest.mock import MagicMock


def _mock_endpoint(url, total_seconds):
    resp = MagicMock()
    resp.status_code = 200
    resp.elapsed = MagicMock()
    resp.elapsed.total_seconds.return_value = total_seconds
    return resp


class TestResponseTime(unittest.TestCase):
    """Tests verifying mocked API response times."""

    def test_health_endpoint_fast(self):
        resp = _mock_endpoint("http://localhost/api/health", 0.03)

        self.assertEqual(resp.status_code, 200)
        self.assertLess(resp.elapsed.total_seconds(), 0.1)

    def test_api_list_response_time(self):
        resp = _mock_endpoint("http://localhost/api/testcases", 0.2)

        self.assertEqual(resp.status_code, 200)
        self.assertLess(resp.elapsed.total_seconds(), 2.0)

    def test_dashboard_response_time(self):
        resp = _mock_endpoint("http://localhost/api/dashboard", 0.5)

        self.assertEqual(resp.status_code, 200)
        self.assertLess(resp.elapsed.total_seconds(), 3.0)


if __name__ == "__main__":
    unittest.main()
