"""Centralized error handlers for the QA platform.

This module provides reusable error handler registration and custom
exception classes. It is designed to be imported by the application factory
(__init__.py) or used standalone for blueprints that need their own error
handling.
"""

import logging

from flask import jsonify, render_template, request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception classes
# ---------------------------------------------------------------------------


class AppError(Exception):
    """Base application error with status code and user-facing message."""

    def __init__(self, message: str, status_code: int = 500, payload: dict | None = None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict."""
        rv = dict(self.payload)
        rv["error"] = self.__class__.__name__
        rv["message"] = self.message
        return rv


class NotFoundError(AppError):
    """Resource not found (404)."""

    def __init__(self, message: str = "Resource not found.", payload: dict | None = None):
        super().__init__(message, 404, payload)


class ForbiddenError(AppError):
    """Access denied (403)."""

    def __init__(self, message: str = "You do not have permission to perform this action.", payload: dict | None = None):
        super().__init__(message, 403, payload)


class BadRequestError(AppError):
    """Invalid request data (400)."""

    def __init__(self, message: str = "Invalid request.", payload: dict | None = None):
        super().__init__(message, 400, payload)


class ConflictError(AppError):
    """Resource conflict (409)."""

    def __init__(self, message: str = "Resource conflict.", payload: dict | None = None):
        super().__init__(message, 409, payload)


# ---------------------------------------------------------------------------
# Error handler registration
# ---------------------------------------------------------------------------


def _is_browser_request() -> bool:
    """Return True if the Accept header indicates a browser."""
    accept = request.headers.get("Accept", "")
    return "text/html" in accept


def register_error_handlers(app) -> None:
    """Register all error handlers on the Flask app.

    Browser requests receive rendered HTML templates.
    API / non-browser requests receive JSON.
    """

    @app.errorhandler(AppError)
    def handle_app_error(error):
        """Handle custom application errors."""
        logger.warning("AppError: %s (status=%d)", error.message, error.status_code)
        if _is_browser_request():
            if error.status_code == 403:
                return render_template("errors/403.html"), 403
            if error.status_code == 404:
                return render_template("errors/404.html"), 404
            return jsonify(error.to_dict()), error.status_code
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(400)
    def bad_request(error):
        logger.warning("400 Bad Request: %s", request.url)
        if _is_browser_request():
            return render_template("errors/404.html"), 400
        return jsonify({"error": "Bad Request", "message": "The request was invalid."}), 400

    @app.errorhandler(403)
    def forbidden(error):
        logger.warning("403 Forbidden: %s", request.url)
        if _is_browser_request():
            return render_template("errors/403.html"), 403
        return jsonify({"error": "Forbidden", "message": "You do not have permission to access this resource."}), 403

    @app.errorhandler(404)
    def not_found(error):
        logger.info("404 Not Found: %s", request.url)
        if _is_browser_request():
            return render_template("errors/404.html"), 404
        return jsonify({"error": "Not Found", "message": "The requested resource was not found."}), 404

    @app.errorhandler(429)
    def rate_limited(error):
        logger.warning("429 Rate Limited: %s", request.url)
        if _is_browser_request():
            return jsonify({"error": "Too Many Requests", "message": "Rate limit exceeded. Please try again later."}), 429
        return jsonify({"error": "Too Many Requests", "message": "Rate limit exceeded. Please try again later."}), 429

    @app.errorhandler(500)
    def internal_error(error):
        from app.extensions import db

        logger.exception("500 Internal Server Error: %s", request.url)
        db.session.rollback()
        if _is_browser_request():
            return render_template("errors/404.html"), 500
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error has occurred."}), 500
