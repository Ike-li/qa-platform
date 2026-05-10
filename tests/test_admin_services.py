"""Tests for app/admin/services.py – direct service-layer tests."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


from app.admin.services import (
    _delete_report_files,
    enforce_retention,
    validate_all_configs,
    validate_config_value,
)
from app.models.allure_report import AllureReport
from app.models.audit_log import AuditLog
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.system_config import SystemConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_execution(db, project, created_at, status=ExecutionStatus.COMPLETED):
    ex = Execution(
        project_id=project.id,
        status=status,
        trigger_type=TriggerType.WEB,
        created_at=created_at,
        finished_at=created_at + timedelta(hours=1)
        if status == ExecutionStatus.COMPLETED
        else None,
    )
    db.session.add(ex)
    db.session.commit()
    return ex


def _create_report(
    db,
    execution,
    generated_at,
    report_path="/tmp/report",
    report_url="https://example.com/report",
):
    r = AllureReport(
        execution_id=execution.id,
        report_path=report_path,
        report_url=report_url,
        generated_at=generated_at,
    )
    db.session.add(r)
    db.session.commit()
    return r


def _create_audit_log(db, action, created_at, username="system"):
    log = AuditLog(
        action=action,
        username=username,
        created_at=created_at,
    )
    db.session.add(log)
    db.session.commit()
    return log


NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# TestValidateConfigValue
# ===========================================================================


class TestValidateConfigValue:
    def test_unknown_key_no_rules(self):
        ok, msg = validate_config_value("unknown.key", "anything")
        assert ok is True
        assert msg == ""

    def test_valid_int(self):
        ok, msg = validate_config_value("execution.timeout_minutes", "30")
        assert ok is True
        assert msg == ""

    def test_non_int_string(self):
        ok, msg = validate_config_value("execution.timeout_minutes", "abc")
        assert ok is False
        assert "must be an integer" in msg

    def test_below_minimum(self):
        ok, msg = validate_config_value("execution.timeout_minutes", "0")
        assert ok is False
        assert "must be >= 1" in msg

    def test_above_maximum(self):
        ok, msg = validate_config_value("execution.timeout_minutes", "1441")
        assert ok is False
        assert "must be <= 1440" in msg

    def test_valid_smtp_port(self):
        ok, msg = validate_config_value("notification.smtp_port", "587")
        assert ok is True
        assert msg == ""

    def test_smtp_port_above_max(self):
        ok, msg = validate_config_value("notification.smtp_port", "70000")
        assert ok is False
        assert "must be <= 65535" in msg

    def test_exact_boundary_min(self):
        ok, msg = validate_config_value("execution.max_parallel", "1")
        assert ok is True
        assert msg == ""

    def test_exact_boundary_max(self):
        ok, msg = validate_config_value("execution.max_parallel", "20")
        assert ok is True
        assert msg == ""


# ===========================================================================
# TestValidateAllConfigs
# ===========================================================================


class TestValidateAllConfigs:
    def test_all_valid(self):
        ok, errors = validate_all_configs(
            {
                "execution.timeout_minutes": "30",
                "execution.max_parallel": "5",
            }
        )
        assert ok is True
        assert errors == {}

    def test_mix_valid_and_invalid(self):
        ok, errors = validate_all_configs(
            {
                "execution.timeout_minutes": "30",
                "execution.max_parallel": "abc",
            }
        )
        assert ok is False
        assert "execution.max_parallel" in errors
        assert "must be an integer" in errors["execution.max_parallel"]

    def test_all_invalid(self):
        ok, errors = validate_all_configs(
            {
                "execution.timeout_minutes": "xyz",
                "execution.max_parallel": "0",
            }
        )
        assert ok is False
        assert len(errors) == 2

    def test_empty_dict(self):
        ok, errors = validate_all_configs({})
        assert ok is True
        assert errors == {}


# ===========================================================================
# TestDeleteReportFiles
# ===========================================================================


class TestDeleteReportFiles:
    def test_existing_directory_removed(self, tmp_path):
        report_dir = tmp_path / "report_dir"
        report_dir.mkdir()
        (report_dir / "index.html").write_text("<html></html>")
        _delete_report_files(str(report_dir))
        assert not report_dir.exists()

    def test_nonexistent_path_no_exception(self):
        _delete_report_files("/nonexistent/path/abc123")

    def test_empty_string_no_exception(self):
        _delete_report_files("")

    def test_none_no_exception(self):
        _delete_report_files(None)

    def test_oserror_no_exception(self, tmp_path, monkeypatch):
        def raise_oserror(path):
            raise OSError("permission denied")

        monkeypatch.setattr("shutil.rmtree", raise_oserror)
        # Create a real directory so os.path.isdir returns True
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        _delete_report_files(str(report_dir))  # Should not raise


# ===========================================================================
# TestEnforceRetention
# ===========================================================================


class TestEnforceRetention:
    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_old_execution_deleted(self, mock_dt, mock_delete, app, db, sample_project):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        old_time = NOW - timedelta(days=200)
        ex = _create_execution(db, sample_project, old_time)

        result = enforce_retention()
        assert result["executions_deleted"] == 1
        assert Execution.query.filter_by(id=ex.id).count() == 0

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_old_standalone_report_deleted(
        self, mock_dt, mock_delete, app, db, sample_project
    ):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        # Create a recent execution (won't be deleted by execution retention)
        recent_time = NOW - timedelta(days=5)
        ex = _create_execution(db, sample_project, recent_time)

        # But the report is old (standalone report retention = 30 days default)
        old_report_time = NOW - timedelta(days=60)
        _create_report(db, ex, old_report_time)

        result = enforce_retention()
        assert result["reports_deleted"] == 1

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_old_audit_logs_deleted(
        self, mock_dt, mock_delete, app, db, sample_project
    ):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        old_time = NOW - timedelta(days=200)
        _create_audit_log(db, "test.old", old_time)

        result = enforce_retention()
        assert result["audit_deleted"] == 1

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_no_expired_data(self, mock_dt, mock_delete, app, db, sample_project):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        recent = NOW - timedelta(days=5)
        _create_execution(db, sample_project, recent)
        _create_audit_log(db, "test.recent", recent)

        result = enforce_retention()
        assert result["executions_deleted"] == 0
        assert result["reports_deleted"] == 0
        assert result["audit_deleted"] == 0

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_disabled_execution_retention(
        self, mock_dt, mock_delete, app, db, sample_project
    ):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        db.session.add(
            SystemConfig(key="retention.execution_days", value="0", value_type="int")
        )
        db.session.commit()

        old_time = NOW - timedelta(days=200)
        _create_execution(db, sample_project, old_time)

        result = enforce_retention()
        assert result["executions_deleted"] == 0

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_disabled_report_retention(
        self, mock_dt, mock_delete, app, db, sample_project
    ):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        db.session.add(
            SystemConfig(key="retention.report_days", value="0", value_type="int")
        )
        db.session.commit()

        recent_time = NOW - timedelta(days=5)
        ex = _create_execution(db, sample_project, recent_time)
        old_report_time = NOW - timedelta(days=60)
        _create_report(db, ex, old_report_time)

        result = enforce_retention()
        assert result["reports_deleted"] == 0

    @patch("app.admin.services._delete_report_files")
    @patch("app.admin.services.datetime")
    def test_disabled_audit_retention(
        self, mock_dt, mock_delete, app, db, sample_project
    ):
        mock_dt.now.return_value = NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        db.session.add(
            SystemConfig(key="retention.audit_days", value="0", value_type="int")
        )
        db.session.commit()

        old_time = NOW - timedelta(days=200)
        _create_audit_log(db, "test.old", old_time)

        result = enforce_retention()
        assert result["audit_deleted"] == 0
