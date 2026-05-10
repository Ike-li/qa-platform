"""Tests for app/utils/audit.py — log_audit utility."""

from datetime import datetime
from unittest.mock import patch, MagicMock, PropertyMock


from app.models.audit_log import AuditLog
from app.utils.audit import log_audit


class TestLogAudit:
    def test_creates_record_with_explicit_user(self, app, db):
        entry = log_audit(
            action="test.action",
            resource_type="project",
            resource_id="1",
            username="tester",
            user_id=99,
        )
        assert entry.id is not None
        assert entry.action == "test.action"
        assert entry.resource_type == "project"
        assert entry.resource_id == "1"
        assert entry.username == "tester"
        assert entry.user_id == 99

    def test_defaults_username_to_system(self, app, db):
        entry = log_audit(action="test.default_user")
        assert entry.username == "system"

    def test_resource_id_none_stays_none(self, app, db):
        entry = log_audit(
            action="test.no_resource",
            resource_type=None,
            resource_id=None,
        )
        assert entry.resource_type is None
        assert entry.resource_id is None

    def test_resource_id_converted_to_string(self, app, db):
        entry = log_audit(
            action="test.convert",
            resource_id=123,
        )
        assert entry.resource_id == "123"

    def test_old_value_and_new_value(self, app, db):
        entry = log_audit(
            action="test.values",
            old_value={"status": "open"},
            new_value={"status": "closed"},
        )
        assert entry.old_value == {"status": "open"}
        assert entry.new_value == {"status": "closed"}

    def test_captures_request_context(self, client, db):
        resp = client.get(
            "/audit-ctx",
            headers={"User-Agent": "TestAgent/1.0"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ua"] == "TestAgent/1.0"

    def test_user_agent_truncated_to_256(self, client, db):
        long_ua = "A" * 500
        resp = client.get("/audit-ua-trunc", headers={"User-Agent": long_ua})
        assert resp.status_code == 200
        assert len(resp.get_json()["ua"]) == 256

    def test_ip_address_captured(self, client, db):
        resp = client.get("/audit-ip")
        data = resp.get_json()
        assert data["ip"] == "127.0.0.1"

    def test_created_at_is_set(self, app, db):
        entry = log_audit(action="test.time")
        assert isinstance(entry.created_at, datetime)

    def test_entry_committed_to_db(self, app, db):
        entry = log_audit(action="test.commit")
        db.session.expire_all()
        found = db.session.get(AuditLog, entry.id)
        assert found is not None
        assert found.action == "test.commit"

    def test_no_request_context_fallback(self, app, db):
        entry = log_audit(action="test.no_request")
        assert entry.action == "test.no_request"

    def test_username_override(self, app, db):
        entry = log_audit(
            action="test.override",
            username="override_user",
            user_id=42,
        )
        assert entry.username == "override_user"
        assert entry.user_id == 42

    def test_repr(self, app, db):
        entry = log_audit(
            action="test.repr",
            resource_type="project",
            resource_id="5",
            username="alice",
        )
        r = repr(entry)
        assert "test.repr" in r
        assert "alice" in r
        assert "project" in r
        assert "5" in r


# ---------------------------------------------------------------------------
# current_user fallback branches (lines 41-43, 50-51, 57-58 in audit.py)
# ---------------------------------------------------------------------------


class TestCurrentUserFallback:
    def test_current_user_fallback_authenticated(self, app, db):
        """When current_user is authenticated, user_id and username are resolved."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 42
        mock_user.username = "mockuser"

        with patch("app.utils.audit.current_user", mock_user):
            entry = log_audit(action="test.auth")

        assert entry.user_id == 42
        assert entry.username == "mockuser"

    def test_current_user_id_access_raises(self, app, db):
        """When accessing current_user.id raises, user_id stays None."""
        mock_user = MagicMock()
        type(mock_user).is_authenticated = PropertyMock(
            side_effect=RuntimeError("proxy")
        )

        with patch("app.utils.audit.current_user", mock_user):
            entry = log_audit(action="test.err")

        assert entry.user_id is None
        assert entry.username == "system"

    def test_current_user_username_access_raises(self, app, db):
        """When accessing current_user.username raises, username defaults to 'system'."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = 1
        type(mock_user).username = PropertyMock(side_effect=RuntimeError("proxy"))

        with patch("app.utils.audit.current_user", mock_user):
            entry = log_audit(action="test.err2")

        assert entry.username == "system"

    def test_request_runtime_error_fallback(self, app, db):
        """When request.remote_addr raises RuntimeError, ip and ua are None."""
        mock_request = MagicMock()
        type(mock_request).remote_addr = PropertyMock(side_effect=RuntimeError("ctx"))

        with patch("app.utils.audit.request", mock_request):
            entry = log_audit(action="test.req_err")

        assert entry.ip_address is None
        assert entry.user_agent is None
