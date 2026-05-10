"""Tests for auth edge cases -- uncovered branches in auth/routes.py.

Covers: rate limiting, Redis cleanup, safe URL validation,
        profile email update, _parse_test_names error handling.
"""

from unittest.mock import patch, MagicMock


# ===========================================================================
# Auth rate limiting
# ===========================================================================


class TestAuthRateLimiting:
    @patch("app.auth.routes._check_login_rate_limit")
    def test_rate_limit_blocks_login(self, mock_limit, client, admin_user, db):
        """Rate limit returning False renders 429 page."""
        mock_limit.return_value = False
        resp = client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        assert resp.status_code == 429
        assert "过多".encode() in resp.data or b"rate" in resp.data.lower()

    @patch("redis.from_url")
    def test_check_login_rate_limit_success(self, mock_from_url, app, db):
        """Rate limit check succeeds when count is under limit."""
        mock_r = MagicMock()
        mock_r.incr.return_value = 3
        mock_from_url.return_value = mock_r

        from app.auth.routes import _check_login_rate_limit

        result = _check_login_rate_limit("127.0.0.1")
        assert result is True

    @patch("redis.from_url")
    def test_check_login_rate_limit_exceeded(self, mock_from_url, app, db):
        """Rate limit check fails when count exceeds limit."""
        mock_r = MagicMock()
        mock_r.incr.return_value = 6
        mock_from_url.return_value = mock_r

        from app.auth.routes import _check_login_rate_limit

        result = _check_login_rate_limit("127.0.0.1")
        assert result is False

    @patch("redis.from_url")
    def test_check_login_rate_limit_redis_failure(self, mock_from_url, app, db):
        """Rate limit allows login when Redis is down."""
        mock_from_url.side_effect = RuntimeError("redis down")

        from app.auth.routes import _check_login_rate_limit

        result = _check_login_rate_limit("127.0.0.1")
        assert result is True

    @patch("redis.from_url")
    def test_check_login_rate_limit_first_request(self, mock_from_url, app, db):
        """First request sets expiry on the key."""
        mock_r = MagicMock()
        mock_r.incr.return_value = 1  # first request
        mock_from_url.return_value = mock_r

        from app.auth.routes import _check_login_rate_limit

        result = _check_login_rate_limit("127.0.0.1")
        assert result is True
        mock_r.expire.assert_called_once()


# ===========================================================================
# Safe URL validation
# ===========================================================================


class TestIsSafeUrl:
    def test_unsafe_url_relative_path(self, app):
        """Relative URLs (no scheme) are rejected."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("/dashboard") is False

    def test_safe_url_absolute_same_host(self, app):
        """Absolute URL to same host is safe."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("http://localhost/other") is True

    def test_safe_url_https_same_host(self, app):
        """HTTPS URL to same host is safe."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("https://localhost/other") is True

    def test_unsafe_url_different_host(self, app):
        """URL to different host is unsafe."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("http://evil.com/steal") is False

    def test_unsafe_url_none(self, app):
        """None is unsafe."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url(None) is False

    def test_unsafe_url_empty(self, app):
        """Empty string is unsafe."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("") is False

    def test_unsafe_url_javascript_scheme(self, app):
        """javascript: scheme is not in allowed list."""
        from app.auth.routes import _is_safe_url

        with app.test_request_context("http://localhost/test"):
            assert _is_safe_url("javascript:alert(1)") is False


# ===========================================================================
# Profile edge cases
# ===========================================================================


class TestProfileEdgeCases:
    def test_profile_email_update(self, client, login_as_admin, admin_user, db):
        """Changing only email succeeds."""
        resp = client.post(
            "/auth/profile",
            data={
                "email": "newemail@test.com",
                "current_password": "",
                "new_password": "",
                "confirm_password": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db as _db

        _db.session.expire_all()
        updated = _db.session.get(type(admin_user), admin_user.id)
        assert updated.email == "newemail@test.com"

    def test_profile_password_no_current(self, client, login_as_admin, db):
        """Setting new password without current password fails."""
        resp = client.post(
            "/auth/profile",
            data={
                "email": "admin@test.com",
                "current_password": "",
                "new_password": "NewPass123",
                "confirm_password": "NewPass123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200  # Re-renders form

    def test_profile_password_wrong_current(self, client, login_as_admin, db):
        """Wrong current password re-renders form."""
        resp = client.post(
            "/auth/profile",
            data={
                "email": "admin@test.com",
                "current_password": "wrongcurrent",
                "new_password": "NewPass123",
                "confirm_password": "NewPass123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 200


# ===========================================================================
# _parse_test_names edge cases (projects/services.py)
# ===========================================================================


class TestParseTestNames:
    def test_parse_syntax_error(self, app, tmp_path):
        """SyntaxError in test file returns empty list."""
        from app.projects.services import _parse_test_names

        bad_file = tmp_path / "test_bad.py"
        bad_file.write_text("def test_ok(\n")  # syntax error
        result = _parse_test_names(str(bad_file))
        assert result == []

    def test_parse_os_error(self, app):
        """OSError (nonexistent file) returns empty list."""
        from app.projects.services import _parse_test_names

        result = _parse_test_names("/nonexistent/test_fake.py")
        assert result == []

    def test_parse_no_test_functions(self, app, tmp_path):
        """File with no test_ functions returns empty list."""
        from app.projects.services import _parse_test_names

        f = tmp_path / "test_empty.py"
        f.write_text("def helper(): pass\n")
        result = _parse_test_names(str(f))
        assert result == []

    def test_parse_class_methods_skipped(self, app, tmp_path):
        """test_ methods inside classes are still found by ast.walk."""
        from app.projects.services import _parse_test_names

        f = tmp_path / "test_class.py"
        f.write_text(
            "class TestFoo:\n"
            "    def test_bar(self): pass\n"
            "    def test_baz(self): pass\n"
        )
        result = _parse_test_names(str(f))
        assert "test_bar" in result
        assert "test_baz" in result

    def test_parse_encoding_error(self, app, tmp_path):
        """File with encoding issues returns empty list gracefully."""
        from app.projects.services import _parse_test_names

        bad_file = tmp_path / "test_binary.py"
        bad_file.write_bytes(b"\xff\xfe\x00\x01")
        result = _parse_test_names(str(bad_file))
        # Should not raise, may return empty or partial
        assert isinstance(result, list)


# ===========================================================================
# Auth decorator edge cases (unauthenticated redirect)
# ===========================================================================


class TestDecoratorsEdgeCases:
    """Test permission_required and project_permission_required decorators
    with unauthenticated users, using a dedicated minimal Flask app."""

    def _make_decorated_app(self):
        """Create a minimal Flask app with LoginManager and decorated routes."""
        from flask import Flask
        from flask_login import LoginManager

        from app.auth import auth_bp
        from app.auth.decorators import permission_required, project_permission_required

        test_app = Flask(__name__)
        test_app.config["SECRET_KEY"] = "test-secret"
        test_app.config["TESTING"] = True

        login_manager = LoginManager()
        login_manager.login_view = "auth.login"
        login_manager.init_app(test_app)

        @login_manager.user_loader
        def load_user(user_id):
            return None

        test_app.register_blueprint(auth_bp)

        @test_app.route("/test-perm")
        @permission_required("test", "perm")
        def perm_route():
            return "ok"

        @test_app.route("/test-proj/<int:project_id>")
        @project_permission_required("test.perm")
        def proj_perm_route(project_id):
            return "ok"

        return test_app

    def test_permission_required_unauthenticated_redirect(self):
        """Unauthenticated user accessing @permission_required redirects to login."""
        test_app = self._make_decorated_app()
        client = test_app.test_client()
        resp = client.get("/test-perm", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]

    def test_project_permission_required_unauthenticated_redirect(self):
        """Unauthenticated user accessing @project_permission_required redirects to login."""
        test_app = self._make_decorated_app()
        client = test_app.test_client()
        resp = client.get("/test-proj/1", follow_redirects=False)
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers["Location"]
