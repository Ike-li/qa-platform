import unittest
from unittest.mock import MagicMock


class TestLoginPage(unittest.TestCase):
    """Tests for the login page using mocked Playwright page object."""

    def _make_page(self):
        page = MagicMock()
        page.url = "http://localhost/login"
        return page

    def test_login_form_renders(self):
        page = self._make_page()
        page.goto("http://localhost/login")

        page.fill("input[name='username']", "user@test.com")
        page.fill("input[name='password']", "secret")

        page.fill.assert_any_call("input[name='username']", "user@test.com")
        page.fill.assert_any_call("input[name='password']", "secret")
        self.assertEqual(page.fill.call_count, 2)

    def test_login_submit_success(self):
        page = self._make_page()
        page.click("button[type='submit']")
        page.url = "http://localhost/dashboard"

        page.click.assert_called_once_with("button[type='submit']")
        self.assertEqual(page.url, "http://localhost/dashboard")
        self.assertNotIn("login", page.url)

    def test_login_submit_invalid(self):
        page = self._make_page()
        page.query_selector.return_value.inner_text.return_value = "Invalid credentials"
        error_el = page.query_selector(".error-message")

        self.assertIsNotNone(error_el)
        self.assertEqual(error_el.inner_text(), "Invalid credentials")
        page.query_selector.assert_called_with(".error-message")

    def test_login_redirect(self):
        page = self._make_page()
        page.goto("http://localhost/login")
        page.click("button[type='submit']")
        page.url = "http://localhost/dashboard"

        self.assertTrue(page.url.endswith("/dashboard"))


if __name__ == "__main__":
    unittest.main()
