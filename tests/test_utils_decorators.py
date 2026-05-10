"""Tests for app/utils/decorators.py — audit_log decorator."""

from unittest.mock import patch

from flask import jsonify

from app.models.audit_log import AuditLog
from app.utils.decorators import audit_log


class TestAuditLogDecorator:
    """Tests use pre-registered routes from conftest that apply @audit_log
    inside the view function body, bypassing Flask's route registration
    restriction.  All routes are registered once in conftest._app."""

    def test_decorator_logs_action(self, client):
        resp = client.get("/dec-audit-action")
        assert resp.status_code == 200
        entry = AuditLog.query.filter_by(action="test.action").first()
        assert entry is not None

    def test_decorator_extracts_resource_type_and_id(self, client):
        resp = client.get("/dec-resource/project/42")
        assert resp.status_code == 200
        entry = AuditLog.query.filter_by(action="test.resource").first()
        assert entry is not None
        assert entry.resource_type == "project"
        assert entry.resource_id == "42"

    def test_decorator_extracts_id_fallback(self, client):
        resp = client.get("/dec-items/99")
        assert resp.status_code == 200
        entry = AuditLog.query.filter_by(action="test.item").first()
        assert entry is not None
        assert entry.resource_id == "99"

    def test_decorator_no_view_args(self, client):
        resp = client.get("/dec-no-args")
        assert resp.status_code == 200
        entry = AuditLog.query.filter_by(action="test.noargs").first()
        assert entry is not None
        assert entry.resource_type is None
        assert entry.resource_id is None

    def test_decorator_returns_view_response(self, client):
        resp = client.get("/dec-return-201")
        assert resp.status_code == 201
        assert resp.get_json()["custom"] == "data"

    def test_decorator_audit_failure_does_not_break_view(self, client):
        # Patch at the source module where log_audit is imported from,
        # since the decorator does a deferred import inside the wrapper.
        with patch(
            "app.utils.audit.log_audit",
            side_effect=RuntimeError("db down"),
        ):
            resp = client.get("/dec-fail-audit")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_decorator_preserves_function_name(self):
        @audit_log("test.preserve")
        def my_view_function():
            return jsonify({"ok": True})

        assert my_view_function.__name__ == "my_view_function"

    def test_decorator_with_kwargs(self, client):
        resp = client.get("/dec-kwargs/suite")
        assert resp.status_code == 200
        entry = AuditLog.query.filter_by(action="test.kwargs").first()
        assert entry is not None
        assert entry.resource_type == "suite"
