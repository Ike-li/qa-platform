"""Tests for app/utils/errors.py — error handler registration and exception classes."""

from unittest.mock import patch

import pytest
from flask import Flask, abort

from app.utils.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    register_error_handlers,
)


# ---------------------------------------------------------------------------
# Separate Flask app with error handlers + test routes for handler coverage
# ---------------------------------------------------------------------------


@pytest.fixture()
def error_app():
    """Create a fresh Flask app with error handlers and test routes registered.

    This avoids conflicting with the session-scoped _app which may have
    already handled requests by the time this module's fixtures run.
    """
    app = Flask(__name__)
    app.config["TESTING"] = True

    # Register error handlers from app.utils.errors (covers lines 84-132)
    register_error_handlers(app)

    @app.route("/test-force-400")
    def _t400():
        abort(400)

    @app.route("/test-force-429")
    def _t429():
        abort(429)

    @app.route("/test-force-app-error")
    def _t_app_err():
        raise AppError("custom", status_code=418)

    @app.route("/test-force-app-error-403")
    def _t_app_err_403():
        raise AppError("forbidden", status_code=403)

    @app.route("/test-force-app-error-404")
    def _t_app_err_404():
        raise NotFoundError()

    @app.route("/test-force-500")
    def _t500():
        abort(500)

    @app.route("/test-force-403")
    def _t403():
        from app.utils.errors import ForbiddenError

        raise ForbiddenError()

    @app.route("/test-force-403-raw")
    def _t403_raw():
        abort(403)

    @app.route("/test-force-404")
    def _t404():
        abort(404)

    return app


# ---------------------------------------------------------------------------
# Exception classes (no app context needed)
# ---------------------------------------------------------------------------


class TestAppError:
    def test_default_status_code(self):
        err = AppError("boom")
        assert err.status_code == 500
        assert err.message == "boom"
        assert err.payload == {}

    def test_custom_status_and_payload(self):
        err = AppError("oops", status_code=418, payload={"key": "val"})
        assert err.status_code == 418
        assert err.payload == {"key": "val"}

    def test_to_dict_includes_class_name(self):
        err = AppError("msg", status_code=400)
        d = err.to_dict()
        assert d["error"] == "AppError"
        assert d["message"] == "msg"

    def test_to_dict_merges_payload(self):
        err = AppError("msg", payload={"extra": 42})
        d = err.to_dict()
        assert d["extra"] == 42
        assert d["error"] == "AppError"

    def test_to_dict_with_none_payload(self):
        err = AppError("msg", payload=None)
        d = err.to_dict()
        assert d == {"error": "AppError", "message": "msg"}


class TestNotFoundError:
    def test_default_message_and_status(self):
        err = NotFoundError()
        assert err.status_code == 404
        assert err.message == "Resource not found."

    def test_custom_message(self):
        err = NotFoundError("nope")
        assert err.message == "nope"
        assert err.status_code == 404

    def test_to_dict_class_name(self):
        assert NotFoundError().to_dict()["error"] == "NotFoundError"


class TestForbiddenError:
    def test_default_message_and_status(self):
        err = ForbiddenError()
        assert err.status_code == 403
        assert "permission" in err.message.lower()

    def test_to_dict_class_name(self):
        assert ForbiddenError().to_dict()["error"] == "ForbiddenError"


class TestBadRequestError:
    def test_default_message_and_status(self):
        err = BadRequestError()
        assert err.status_code == 400
        assert "invalid" in err.message.lower()

    def test_to_dict_class_name(self):
        assert BadRequestError().to_dict()["error"] == "BadRequestError"


class TestConflictError:
    def test_default_message_and_status(self):
        err = ConflictError()
        assert err.status_code == 409
        assert "conflict" in err.message.lower()

    def test_to_dict_class_name(self):
        assert ConflictError().to_dict()["error"] == "ConflictError"


# ---------------------------------------------------------------------------
# Registered error handlers (from app factory: 403, 404, 500)
# ---------------------------------------------------------------------------


class TestRegisteredHandlers:
    """Tests use pre-registered routes from conftest and the app factory's
    own error handlers for 403, 404, and 500 status codes."""

    def test_404_json(self, client):
        resp = client.get("/nonexistent-path-xyz")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Not Found"
        assert "resource" in data["message"].lower()

    def test_404_html(self, client):
        resp = client.get("/nonexistent-path-xyz", headers={"Accept": "text/html"})
        assert resp.status_code == 404

    def test_403_json(self, app, client):
        resp = client.get("/test-force-403")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "Forbidden"
        assert "permission" in data["message"].lower()

    def test_403_html(self, app, client):
        resp = client.get("/test-force-403", headers={"Accept": "text/html"})
        assert resp.status_code == 403

    def test_500_json(self, client):
        resp = client.get("/test-force-500")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"] == "Internal Server Error"

    def test_500_html(self, client):
        resp = client.get("/test-force-500", headers={"Accept": "text/html"})
        assert resp.status_code == 500


class TestIsBrowserRequest:
    def test_html_accept(self, app):
        with app.test_request_context("/", headers={"Accept": "text/html"}):
            from app.utils.errors import _is_browser_request

            assert _is_browser_request() is True

    def test_json_accept(self, app):
        with app.test_request_context("/", headers={"Accept": "application/json"}):
            from app.utils.errors import _is_browser_request

            assert _is_browser_request() is False

    def test_empty_accept(self, app):
        with app.test_request_context("/"):
            from app.utils.errors import _is_browser_request

            assert _is_browser_request() is False

    def test_mixed_accept(self, app):
        with app.test_request_context(
            "/", headers={"Accept": "text/html, application/json"}
        ):
            from app.utils.errors import _is_browser_request

            assert _is_browser_request() is True


# ---------------------------------------------------------------------------
# Additional error handler coverage: 400, 429, AppError (418/403/404)
# Uses the dedicated error_app fixture to avoid conflicting with the
# session-scoped _app that may have already handled requests.
# ---------------------------------------------------------------------------


class Test400Handler:
    def test_400_json(self, error_app):
        with error_app.test_client() as client:
            resp = client.get("/test-force-400", headers={"Accept": "application/json"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "Bad Request"
        assert "invalid" in data["message"].lower()

    def test_400_html(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>400</html>"
            ):
                resp = client.get("/test-force-400", headers={"Accept": "text/html"})
        assert resp.status_code == 400


class Test429Handler:
    def test_429_json(self, error_app):
        with error_app.test_client() as client:
            resp = client.get("/test-force-429", headers={"Accept": "application/json"})
        assert resp.status_code == 429
        data = resp.get_json()
        assert data["error"] == "Too Many Requests"
        assert "rate limit" in data["message"].lower()

    def test_429_html(self, error_app):
        with error_app.test_client() as client:
            # The 429 handler returns JSON even for browser requests per the implementation
            resp = client.get("/test-force-429", headers={"Accept": "text/html"})
        assert resp.status_code == 429


class TestAppErrorHandler:
    def test_app_error_418_json(self, error_app):
        with error_app.test_client() as client:
            resp = client.get(
                "/test-force-app-error", headers={"Accept": "application/json"}
            )
        assert resp.status_code == 418
        data = resp.get_json()
        assert data["error"] == "AppError"
        assert data["message"] == "custom"

    def test_app_error_403_browser(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>403</html>"
            ):
                resp = client.get(
                    "/test-force-app-error-403", headers={"Accept": "text/html"}
                )
        assert resp.status_code == 403

    def test_app_error_404_browser(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>404</html>"
            ):
                resp = client.get(
                    "/test-force-app-error-404", headers={"Accept": "text/html"}
                )
        assert resp.status_code == 404

    def test_app_error_418_browser_returns_json(self, error_app):
        """AppError(418) with Accept: text/html — falls through to jsonify."""
        with error_app.test_client() as client:
            resp = client.get("/test-force-app-error", headers={"Accept": "text/html"})
        assert resp.status_code == 418
        data = resp.get_json()
        assert data["error"] == "AppError"
        assert data["message"] == "custom"


class Test500Handler:
    def test_500_json(self, error_app):
        with error_app.test_client() as client:
            resp = client.get("/test-force-500", headers={"Accept": "application/json"})
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"] == "Internal Server Error"

    def test_500_html(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>500</html>"
            ):
                resp = client.get("/test-force-500", headers={"Accept": "text/html"})
        assert resp.status_code == 500


class Test403Handler:
    def test_403_json_api(self, error_app):
        with error_app.test_client() as client:
            resp = client.get(
                "/test-force-403-raw", headers={"Accept": "application/json"}
            )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "Forbidden"

    def test_403_html_browser(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>403</html>"
            ):
                resp = client.get(
                    "/test-force-403-raw", headers={"Accept": "text/html"}
                )
        assert resp.status_code == 403


class Test404Handler:
    def test_404_json_api(self, error_app):
        with error_app.test_client() as client:
            resp = client.get("/test-force-404", headers={"Accept": "application/json"})
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Not Found"
        assert "resource" in data["message"].lower()

    def test_404_html_browser(self, error_app):
        with error_app.test_client() as client:
            with patch(
                "app.utils.errors.render_template", return_value="<html>404</html>"
            ):
                resp = client.get("/test-force-404", headers={"Accept": "text/html"})
        assert resp.status_code == 404
