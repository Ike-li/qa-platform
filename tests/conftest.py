"""Shared test fixtures for the QA platform test suite.

Provides:
- App factory with SQLite in-memory database
- Flask test client
- Auth helpers for each role (login_as_admin, login_as_lead, etc.)
- Database setup/teardown per test (drop & recreate all tables)
"""

import os

import pytest

# Force testing configuration BEFORE importing the app
os.environ["FLASK_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TEST_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/15"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/15"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests"
os.environ["FERNET_KEY"] = "ZmVybmV0LXRlc3Qta2V5LTMyY2hhcnMhISE="

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models.user import Role, User  # noqa: E402


# ---------------------------------------------------------------------------
# App & DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _app():
    """Create and configure a test application instance (session-scoped)."""
    application = create_app("testing")

    # Override to use SQLite for tests (portable, no external deps)
    application.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    application.config["LOGIN_DISABLED"] = False
    application.config["SERVER_NAME"] = "localhost.localdomain"

    # Pre-register test-only routes BEFORE any request is handled.
    # Flask blocks route registration after the first request, so all
    # routes that tests need must be declared here at session scope.
    from flask import abort, jsonify

    @application.route("/test-force-403")
    def _test_force_403():
        abort(403)

    @application.route("/test-force-500")
    def _test_force_500():
        abort(500)

    @application.route("/dec-audit-action")
    def _dec_audit_action():
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.action")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/dec-resource/<resource_type>/<resource_id>")
    def _dec_resource(resource_type, resource_id):
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.resource")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/dec-items/<int:id>")
    def _dec_items(id):
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.item")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/dec-no-args")
    def _dec_no_args():
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.noargs")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/dec-return-201")
    def _dec_return_201():
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.return")
        def _view():
            return jsonify({"custom": "data"}), 201

        return _view()

    @application.route("/dec-fail-audit")
    def _dec_fail_audit():
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.fail")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/dec-kwargs/<resource_type>")
    def _dec_kwargs(resource_type):
        from app.utils.decorators import audit_log as _audit_log

        @_audit_log("test.kwargs")
        def _view():
            return jsonify({"ok": True})

        return _view()

    @application.route("/audit-ctx")
    def _audit_ctx():
        from app.utils.audit import log_audit

        entry = log_audit(action="test.ctx")
        return jsonify({"ip": entry.ip_address, "ua": entry.user_agent})

    @application.route("/audit-ua-trunc")
    def _audit_ua_trunc():
        from app.utils.audit import log_audit

        entry = log_audit(action="test.ua")
        return jsonify({"ua": entry.user_agent})

    @application.route("/audit-ip")
    def _audit_ip():
        from app.utils.audit import log_audit

        entry = log_audit(action="test.ip")
        return jsonify({"ip": entry.ip_address})

    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture(scope="function")
def app(_app):
    """Per-test: clean the database by recreating all tables."""
    with _app.app_context():
        # Drop and recreate all tables for a clean slate
        _db.drop_all()
        _db.create_all()
        yield _app


@pytest.fixture(scope="function")
def db(app):
    """Provide the db object inside the app context."""
    with app.app_context():
        yield _db


@pytest.fixture()
def client(app, db):
    """Flask test client with a clean database."""
    return app.test_client()


@pytest.fixture()
def runner(app):
    """Flask CLI test runner."""
    return app.test_cli_runner()


# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------


def _create_user(
    db_session,
    username: str,
    email: str,
    password: str,
    role: Role,
    is_active: bool = True,
) -> User:
    """Create and persist a user with the given attributes."""
    user = User(
        username=username,
        email=email,
        role=role,
        is_active=is_active,
    )
    user.set_password(password)
    db_session.session.add(user)
    db_session.session.commit()
    return user


@pytest.fixture()
def admin_user(db):
    """A super_admin user."""
    return _create_user(db, "admin", "admin@test.com", "admin123", Role.SUPER_ADMIN)


@pytest.fixture()
def lead_user(db):
    """A project_lead user."""
    return _create_user(db, "lead", "lead@test.com", "lead123", Role.PROJECT_LEAD)


@pytest.fixture()
def tester_user(db):
    """A tester user."""
    return _create_user(db, "tester", "tester@test.com", "tester123", Role.TESTER)


@pytest.fixture()
def visitor_user(db):
    """A visitor user."""
    return _create_user(db, "visitor", "visitor@test.com", "visitor123", Role.VISITOR)


@pytest.fixture()
def inactive_user(db):
    """An inactive user."""
    return _create_user(
        db, "inactive", "inactive@test.com", "inactive123", Role.TESTER, is_active=False
    )


# ---------------------------------------------------------------------------
# Auth helper fixtures
# ---------------------------------------------------------------------------


def _login(client, username: str, password: str):
    """Log in via the login form and return the response."""
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


@pytest.fixture()
def login_as_admin(client, admin_user):
    """Log in as the super_admin user. Returns the response."""
    return _login(client, "admin", "admin123")


@pytest.fixture()
def login_as_lead(client, lead_user):
    """Log in as the project_lead user. Returns the response."""
    return _login(client, "lead", "lead123")


@pytest.fixture()
def login_as_tester(client, tester_user):
    """Log in as the tester user. Returns the response."""
    return _login(client, "tester", "tester123")


@pytest.fixture()
def login_as_visitor(client, visitor_user):
    """Log in as the visitor user. Returns the response."""
    return _login(client, "visitor", "visitor123")


# ---------------------------------------------------------------------------
# Project fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_project(db, admin_user):
    """A sample project owned by the admin user."""
    from app.models.project import Project

    project = Project(
        name="Test Project",
        description="A sample project for testing",
        git_url="https://github.com/example/test-repo.git",
        git_branch="main",
        owner_id=admin_user.id,
    )
    db.session.add(project)
    db.session.commit()
    return project


# ---------------------------------------------------------------------------
# API token fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_token(db, admin_user):
    """An API token for the admin user."""
    from app.models.api_token import ApiToken

    token, raw = ApiToken.create_token(
        user_id=admin_user.id,
        name="test-token",
    )
    return token, raw
