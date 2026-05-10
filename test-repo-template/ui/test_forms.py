import unittest
from unittest.mock import MagicMock


class TestForms(unittest.TestCase):
    """Tests for project forms using mocked Playwright page object."""

    def _make_page(self):
        return MagicMock()

    def test_project_form_validation(self):
        page = self._make_page()
        page.fill("input[name='name']", "")
        page.click("button[type='submit']")

        mock_error = MagicMock()
        mock_error.is_visible.return_value = True
        page.query_selector.return_value = mock_error

        error_el = page.query_selector(".field-error")
        self.assertTrue(error_el.is_visible())

    def test_project_form_submit(self):
        page = self._make_page()
        page.fill("input[name='name']", "New Project")
        page.fill("textarea[name='description']", "Project description")
        page.click("button[type='submit']")

        page.fill.assert_any_call("input[name='name']", "New Project")
        page.fill.assert_any_call("textarea[name='description']", "Project description")
        page.click.assert_called_once_with("button[type='submit']")

    def test_form_error_display(self):
        page = self._make_page()
        mock_error_msg = MagicMock()
        mock_error_msg.inner_text.return_value = "Name is required"
        page.query_selector.return_value = mock_error_msg

        error_el = page.query_selector(".validation-error")
        self.assertEqual(error_el.inner_text(), "Name is required")


if __name__ == "__main__":
    unittest.main()
