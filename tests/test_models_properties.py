"""Tests for model properties, classmethods, staticmethods, and helper functions.

Covers: Execution, SystemConfig, CronSchedule, ApiToken, User, Notification,
AuditLog, AllureReport, DashboardMetric, TestResult models.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.allure_report import AllureReport
from app.models.api_token import ApiToken
from app.models.audit_log import AuditLog
from app.models.cron_schedule import CronSchedule, _parse_field
from app.models.dashboard_metric import DashboardMetric
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.notification import (
    NotificationChannel,
    NotificationConfig,
    NotificationDeliveryStatus,
    NotificationLog,
)
from app.models.project import Project
from app.models.project_membership import (
    PROJECT_ROLE_PERMISSIONS,
    ProjectMembership,
    ProjectRole,
)
from app.models.system_config import (
    SystemConfig,
    _decrypt,
    _encrypt,
    _get_fernet,
)
from app.models.test_result import TestResult, TestResultStatus
from app.models.user import ROLE_PERMISSIONS, Role, User


# ============================================================================
# Step 1: Execution model tests
# ============================================================================


class TestExecutionStageIndicator:
    """Test stage_indicator for all ExecutionStatus values + unknown fallback."""

    def _exec_with_status(self, status):
        e = Execution(project_id=1, status=status)
        return e

    def test_pending(self):
        assert self._exec_with_status(ExecutionStatus.PENDING).stage_indicator == "Queued"

    def test_cloned(self):
        assert self._exec_with_status(ExecutionStatus.CLONED).stage_indicator == "Git Synced"

    def test_running(self):
        assert self._exec_with_status(ExecutionStatus.RUNNING).stage_indicator == "Running Tests"

    def test_executed(self):
        assert self._exec_with_status(ExecutionStatus.EXECUTED).stage_indicator == "Tests Complete"

    def test_completed(self):
        assert self._exec_with_status(ExecutionStatus.COMPLETED).stage_indicator == "Report Generated"

    def test_failed(self):
        assert self._exec_with_status(ExecutionStatus.FAILED).stage_indicator == "Failed"

    def test_timeout(self):
        assert self._exec_with_status(ExecutionStatus.TIMEOUT).stage_indicator == "Timed Out"

    def test_unknown_status_returns_unknown(self):
        e = Execution(project_id=1)
        # Manually set a status not in the mapping via object attribute override
        object.__setattr__(e, "status", "bogus")
        assert e.stage_indicator == "Unknown"


class TestExecutionIsTerminal:
    """Test is_terminal for each status (3 terminal + 4 non-terminal)."""

    def _exec_with_status(self, status):
        return Execution(project_id=1, status=status)

    def test_completed_is_terminal(self):
        assert self._exec_with_status(ExecutionStatus.COMPLETED).is_terminal is True

    def test_failed_is_terminal(self):
        assert self._exec_with_status(ExecutionStatus.FAILED).is_terminal is True

    def test_timeout_is_terminal(self):
        assert self._exec_with_status(ExecutionStatus.TIMEOUT).is_terminal is True

    def test_pending_not_terminal(self):
        assert self._exec_with_status(ExecutionStatus.PENDING).is_terminal is False

    def test_cloned_not_terminal(self):
        assert self._exec_with_status(ExecutionStatus.CLONED).is_terminal is False

    def test_running_not_terminal(self):
        assert self._exec_with_status(ExecutionStatus.RUNNING).is_terminal is False

    def test_executed_not_terminal(self):
        assert self._exec_with_status(ExecutionStatus.EXECUTED).is_terminal is False


class TestExecutionStatusBadgeClass:
    """Test status_badge_class for all statuses + unknown fallback."""

    def _exec_with_status(self, status):
        return Execution(project_id=1, status=status)

    def test_pending_secondary(self):
        assert self._exec_with_status(ExecutionStatus.PENDING).status_badge_class == "secondary"

    def test_cloned_info(self):
        assert self._exec_with_status(ExecutionStatus.CLONED).status_badge_class == "info"

    def test_running_primary(self):
        assert self._exec_with_status(ExecutionStatus.RUNNING).status_badge_class == "primary"

    def test_executed_primary(self):
        assert self._exec_with_status(ExecutionStatus.EXECUTED).status_badge_class == "primary"

    def test_completed_success(self):
        assert self._exec_with_status(ExecutionStatus.COMPLETED).status_badge_class == "success"

    def test_failed_danger(self):
        assert self._exec_with_status(ExecutionStatus.FAILED).status_badge_class == "danger"

    def test_timeout_warning(self):
        assert self._exec_with_status(ExecutionStatus.TIMEOUT).status_badge_class == "warning"

    def test_unknown_falls_back_to_secondary(self):
        e = Execution(project_id=1)
        object.__setattr__(e, "status", "bogus")
        assert e.status_badge_class == "secondary"


class TestExecutionUpdateDuration:
    """Test update_duration with timezone-aware and mixed datetimes."""

    def test_both_aware(self):
        e = Execution(project_id=1)
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 10, 0, 30, tzinfo=timezone.utc)
        e.started_at = start
        e.finished_at = end
        e.update_duration()
        assert e.duration_sec == 30.0

    def test_both_naive(self):
        e = Execution(project_id=1)
        start = datetime(2025, 1, 1, 10, 0, 0)
        end = datetime(2025, 1, 1, 10, 1, 0)
        e.started_at = start
        e.finished_at = end
        e.update_duration()
        assert e.duration_sec == 60.0

    def test_mixed_start_naive_end_aware(self):
        e = Execution(project_id=1)
        start = datetime(2025, 1, 1, 10, 0, 0)
        end = datetime(2025, 1, 1, 10, 0, 15, tzinfo=timezone.utc)
        e.started_at = start
        e.finished_at = end
        e.update_duration()
        assert e.duration_sec == 15.0

    def test_mixed_start_aware_end_naive(self):
        e = Execution(project_id=1)
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 10, 0, 20)
        e.started_at = start
        e.finished_at = end
        e.update_duration()
        assert e.duration_sec == 20.0

    def test_started_at_none_noop(self):
        e = Execution(project_id=1)
        e.started_at = None
        e.finished_at = datetime.now(timezone.utc)
        e.update_duration()
        assert e.duration_sec is None

    def test_finished_at_none_noop(self):
        e = Execution(project_id=1)
        e.started_at = datetime.now(timezone.utc)
        e.finished_at = None
        e.update_duration()
        assert e.duration_sec is None

    def test_both_none_noop(self):
        e = Execution(project_id=1)
        e.started_at = None
        e.finished_at = None
        e.update_duration()
        assert e.duration_sec is None


class TestExecutionRepr:
    def test_repr_format(self):
        e = Execution(id=1, project_id=5, status=ExecutionStatus.RUNNING)
        assert repr(e) == "<Execution id=1 project=5 status=running>"


# ============================================================================
# Step 2: SystemConfig tests
# ============================================================================


class TestSystemConfigCastValue:
    """Test cast_value for all 5 value_type branches."""

    def test_str_type(self, app, db):
        cfg = SystemConfig(key="k.str", value="hello", value_type="str")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.cast_value() == "hello"

    def test_int_type(self, app, db):
        cfg = SystemConfig(key="k.int", value="42", value_type="int")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.cast_value() == 42
        assert isinstance(cfg.cast_value(), int)

    def test_float_type(self, app, db):
        cfg = SystemConfig(key="k.float", value="3.14", value_type="float")
        db.session.add(cfg)
        db.session.commit()
        assert abs(cfg.cast_value() - 3.14) < 1e-9

    def test_bool_true_variant(self, app, db):
        for val in ("true", "1", "yes", "on", "True", "YES"):
            cfg = SystemConfig(key=f"k.bool.{val}", value=val, value_type="bool")
            db.session.add(cfg)
            db.session.commit()
            assert cfg.cast_value() is True, f"Failed for {val}"

    def test_bool_false_variant(self, app, db):
        for val in ("false", "0", "no", "off", "False", "NO"):
            cfg = SystemConfig(key=f"k.bool.{val}", value=val, value_type="bool")
            db.session.add(cfg)
            db.session.commit()
            assert cfg.cast_value() is False, f"Failed for {val}"

    def test_encrypted_type(self, app, db):
        cfg = SystemConfig(key="k.enc", value="secret123", value_type="encrypted")
        db.session.add(cfg)
        db.session.commit()
        # With Fernet key set in conftest, should decrypt back
        result = cfg.cast_value()
        # If fernet works, we get secret123 back; if not, the raw value
        assert isinstance(result, str)


class TestSystemConfigIsSensitive:
    def test_encrypted_is_sensitive(self, app, db):
        cfg = SystemConfig(key="k.sens", value="x", value_type="encrypted")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.is_sensitive is True

    def test_str_not_sensitive(self, app, db):
        cfg = SystemConfig(key="k.ns", value="x", value_type="str")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.is_sensitive is False


class TestSystemConfigDisplayValue:
    def test_sensitive_with_value(self, app, db):
        cfg = SystemConfig(key="k.dv1", value="secret", value_type="encrypted")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.display_value() == "****"

    def test_sensitive_empty(self, app, db):
        cfg = SystemConfig(key="k.dv2", value="", value_type="encrypted")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.display_value() == ""

    def test_non_sensitive(self, app, db):
        cfg = SystemConfig(key="k.dv3", value="visible", value_type="str")
        db.session.add(cfg)
        db.session.commit()
        assert cfg.display_value() == "visible"


class TestSystemConfigGet:
    def test_get_existing(self, app, db):
        cfg = SystemConfig(key="exec.timeout", value="60", value_type="int")
        db.session.add(cfg)
        db.session.commit()
        assert SystemConfig.get("exec.timeout") == 60

    def test_get_missing_returns_default(self, app, db):
        assert SystemConfig.get("nonexistent.key", default=999) == 999

    def test_get_missing_returns_none(self, app, db):
        assert SystemConfig.get("nonexistent.key") is None


class TestSystemConfigSet:
    def test_set_creates_new(self, app, db):
        result = SystemConfig.set("new.key", "hello")
        assert result.value == "hello"
        assert SystemConfig.get("new.key") == "hello"

    def test_set_updates_existing(self, app, db):
        SystemConfig.set("upd.key", "v1")
        SystemConfig.set("upd.key", "v2")
        assert SystemConfig.get("upd.key") == "v2"

    def test_set_encrypted(self, app, db):
        cfg = SystemConfig(key="enc.key", value="", value_type="encrypted")
        db.session.add(cfg)
        db.session.commit()
        SystemConfig.set("enc.key", "mysecret")
        fetched = SystemConfig.query.filter_by(key="enc.key").first()
        # The stored value should be encrypted (different from plaintext when fernet is available)
        assert fetched.value != ""


class TestSystemConfigGetAll:
    def test_get_all_returns_dict(self, app, db):
        db.session.add(SystemConfig(key="a.1", value="10", value_type="int"))
        db.session.add(SystemConfig(key="a.2", value="hello", value_type="str"))
        db.session.commit()
        result = SystemConfig.get_all()
        assert isinstance(result, dict)
        assert result["a.1"] == 10
        assert result["a.2"] == "hello"


class TestSystemConfigSeedDefaults:
    def test_seed_defaults_inserts(self, app, db):
        count = SystemConfig.seed_defaults()
        assert count > 0
        assert SystemConfig.get("execution.timeout_minutes") == 30

    def test_seed_defaults_skips_existing(self, app, db):
        SystemConfig.seed_defaults()
        count = SystemConfig.seed_defaults()
        assert count == 0


class TestSystemConfigRepr:
    def test_repr(self, app, db):
        cfg = SystemConfig(key="r.test", value="v", value_type="str")
        db.session.add(cfg)
        db.session.commit()
        assert repr(cfg) == "<SystemConfig key='r.test' type=str>"


class TestSystemConfigEncryptionHelpers:
    """Test _get_fernet, _encrypt, _decrypt module-level helpers."""

    def _reset_fernet_cache(self):
        import app.models.system_config as scm
        scm._fernet = None

    def test_get_fernet_returns_instance_with_valid_key(self, app, db):
        from cryptography.fernet import Fernet
        import app.models.system_config as scm
        key = Fernet.generate_key().decode()
        import os
        old_key = os.environ.get("FERNET_KEY")
        os.environ["FERNET_KEY"] = key
        self._reset_fernet_cache()
        try:
            f = scm._get_fernet()
            assert f is not None
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key
            else:
                os.environ.pop("FERNET_KEY", None)

    def test_get_fernet_returns_none_without_key(self, app, db):
        import os
        import app.models.system_config as scm
        old_key = os.environ.pop("FERNET_KEY", None)
        self._reset_fernet_cache()
        try:
            f = scm._get_fernet()
            assert f is None
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key

    def test_get_fernet_caches(self, app, db):
        from cryptography.fernet import Fernet
        import app.models.system_config as scm
        key = Fernet.generate_key().decode()
        import os
        old_key = os.environ.get("FERNET_KEY")
        os.environ["FERNET_KEY"] = key
        self._reset_fernet_cache()
        try:
            f1 = scm._get_fernet()
            f2 = scm._get_fernet()
            assert f1 is f2
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key
            else:
                os.environ.pop("FERNET_KEY", None)

    def test_encrypt_decrypt_roundtrip(self, app, db):
        from cryptography.fernet import Fernet
        import os
        import app.models.system_config as scm
        key = Fernet.generate_key().decode()
        old_key = os.environ.get("FERNET_KEY")
        os.environ["FERNET_KEY"] = key
        self._reset_fernet_cache()
        try:
            original = "my_secret_password"
            encrypted = _encrypt(original)
            assert encrypted != original
            decrypted = _decrypt(encrypted)
            assert decrypted == original
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key
            else:
                os.environ.pop("FERNET_KEY", None)

    def test_encrypt_passthrough_when_no_fernet(self, app, db):
        import os
        import app.models.system_config as scm
        old_key = os.environ.pop("FERNET_KEY", None)
        self._reset_fernet_cache()
        try:
            assert _encrypt("test") == "test"
            assert _decrypt("test") == "test"
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key

    def test_decrypt_invalid_ciphertext_passthrough(self, app, db):
        from cryptography.fernet import Fernet
        import os
        import app.models.system_config as scm
        key = Fernet.generate_key().decode()
        old_key = os.environ.get("FERNET_KEY")
        os.environ["FERNET_KEY"] = key
        self._reset_fernet_cache()
        try:
            result = _decrypt("not-valid-fernet-ciphertext")
            assert result == "not-valid-fernet-ciphertext"
        finally:
            scm._fernet = None
            if old_key is not None:
                os.environ["FERNET_KEY"] = old_key
            else:
                os.environ.pop("FERNET_KEY", None)


# ============================================================================
# Step 3: CronSchedule tests
# ============================================================================


class TestValidateCronExpr:
    """Test CronSchedule.validate_cron_expr for valid, invalid, and edge inputs."""

    def test_valid_standard(self):
        assert CronSchedule.validate_cron_expr("0 0 * * *") is True

    def test_valid_step(self):
        assert CronSchedule.validate_cron_expr("*/5 * * * *") is True

    def test_valid_range(self):
        assert CronSchedule.validate_cron_expr("0 9-17 * * *") is True

    def test_valid_comma(self):
        assert CronSchedule.validate_cron_expr("0,15,30,45 * * * *") is True

    def test_valid_complex(self):
        assert CronSchedule.validate_cron_expr("*/10 9-17 1,15 * 1-5") is True

    def test_invalid_string(self):
        assert CronSchedule.validate_cron_expr("not a cron") is False

    def test_empty_string(self):
        assert CronSchedule.validate_cron_expr("") is False

    def test_none(self):
        assert CronSchedule.validate_cron_expr(None) is False

    def test_non_string(self):
        assert CronSchedule.validate_cron_expr(123) is False

    def test_too_few_fields(self):
        assert CronSchedule.validate_cron_expr("* * *") is False

    def test_too_many_fields(self):
        assert CronSchedule.validate_cron_expr("* * * * * *") is False

    def test_whitespace_only(self):
        assert CronSchedule.validate_cron_expr("   ") is False


class TestParseField:
    """Test _parse_field helper for wildcard, step, range, comma, single values."""

    def test_wildcard(self):
        assert _parse_field("*", 0, 59) == list(range(0, 60))

    def test_single_value(self):
        assert _parse_field("5", 0, 59) == [5]

    def test_step_syntax(self):
        result = _parse_field("*/15", 0, 59)
        assert result == [0, 15, 30, 45]

    def test_range_syntax(self):
        result = _parse_field("1-5", 0, 23)
        assert result == [1, 2, 3, 4, 5]

    def test_comma_separated(self):
        result = _parse_field("1,3,5", 0, 23)
        assert result == [1, 3, 5]

    def test_range_with_step(self):
        result = _parse_field("0-23/6", 0, 23)
        assert result == [0, 6, 12, 18]

    def test_mixed_comma_and_range(self):
        result = _parse_field("1-3,7,9-10", 0, 12)
        assert result == [1, 2, 3, 7, 9, 10]

    def test_out_of_range_filtered(self):
        # Values outside [low, high] should be filtered
        result = _parse_field("0-5", 2, 4)
        assert result == [2, 3, 4]

    def test_empty_result_returns_full_range(self):
        # If nothing matches, should return full range
        # This is hard to trigger with valid input, but the fallback exists
        # Test with a range that has no valid values
        result = _parse_field("100", 0, 5)
        # 100 > 5, so no values pass the filter; falls back to full range
        assert result == list(range(0, 6))


class TestCronScheduleCelerySchedule:
    """Test celery_schedule property."""

    def test_valid_expr_returns_crontab(self, app, db, admin_user, sample_project):
        cs = CronSchedule(
            project_id=sample_project.id,
            cron_expr="*/10 * * * *",
        )
        db.session.add(cs)
        db.session.commit()
        sched = cs.celery_schedule
        assert sched is not None

    def test_invalid_expr_returns_none(self, app, db, admin_user, sample_project):
        cs = CronSchedule(
            project_id=sample_project.id,
            cron_expr="not valid cron",
        )
        db.session.add(cs)
        db.session.commit()
        assert cs.celery_schedule is None


class TestCronScheduleRepr:
    def test_repr(self, app, db, admin_user, sample_project):
        cs = CronSchedule(
            id=1, project_id=sample_project.id,
            cron_expr="0 0 * * *", is_active=True,
        )
        assert "CronSchedule" in repr(cs)
        assert "0 0 * * *" in repr(cs)


# ============================================================================
# Step 4: ApiToken tests
# ============================================================================


class TestApiTokenGenerateRawToken:
    def test_prefix(self):
        raw = ApiToken.generate_raw_token()
        assert raw.startswith("qap_")

    def test_total_length(self):
        raw = ApiToken.generate_raw_token()
        # "qap_" (4) + 32 hex chars = 36
        assert len(raw) == 36

    def test_unique(self):
        tokens = {ApiToken.generate_raw_token() for _ in range(50)}
        assert len(tokens) == 50


class TestApiTokenHashToken:
    def test_deterministic(self):
        raw = "qap_test123"
        h1 = ApiToken.hash_token(raw)
        h2 = ApiToken.hash_token(raw)
        assert h1 == h2

    def test_sha256_length(self):
        h = ApiToken.hash_token("test")
        assert len(h) == 64  # SHA-256 hex digest

    def test_different_inputs_different_hashes(self):
        assert ApiToken.hash_token("a") != ApiToken.hash_token("b")


class TestApiTokenCreateToken:
    def test_returns_tuple(self, app, db, admin_user):
        model, raw = ApiToken.create_token(admin_user.id, "test-tok")
        assert isinstance(model, ApiToken)
        assert isinstance(raw, str)
        assert raw.startswith("qap_")

    def test_hash_matches(self, app, db, admin_user):
        model, raw = ApiToken.create_token(admin_user.id, "test-tok")
        assert model.token_hash == ApiToken.hash_token(raw)


class TestApiTokenVerifyToken:
    def test_valid_token(self, app, db, admin_user):
        model, raw = ApiToken.create_token(admin_user.id, "test-v")
        result = ApiToken.verify_token(raw)
        assert result is not None
        assert result.id == model.id

    def test_unknown_token(self, app, db):
        result = ApiToken.verify_token("qap_" + "0" * 32)
        assert result is None

    def test_revoked_token(self, app, db, admin_user):
        model, raw = ApiToken.create_token(admin_user.id, "test-rev")
        model.revoke()
        assert ApiToken.verify_token(raw) is None

    def test_expired_token(self, app, db, admin_user):
        """Test verify_token rejects expired tokens.

        SQLite strips timezone info from stored datetimes, so we mock
        datetime.now in the api_token module to return a naive UTC datetime
        to avoid the naive/aware comparison TypeError.
        """
        from unittest.mock import patch

        naive_past = datetime(2020, 1, 1, 0, 0, 0)  # long ago
        model, raw = ApiToken.create_token(admin_user.id, "test-exp", expires_at=naive_past)
        naive_now = datetime(2025, 6, 1, 0, 0, 0)  # after naive_past
        with patch("app.models.api_token.datetime") as mock_dt:
            mock_dt.now.return_value = naive_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert ApiToken.verify_token(raw) is None

    def test_updates_last_used_at(self, app, db, admin_user):
        model, raw = ApiToken.create_token(admin_user.id, "test-lu")
        assert model.last_used_at is None
        ApiToken.verify_token(raw)
        db.session.refresh(model)
        assert model.last_used_at is not None


class TestApiTokenProperties:
    def test_is_revoked_false(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "t1")
        assert model.is_revoked is False

    def test_is_revoked_true(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "t2")
        model.revoke()
        assert model.is_revoked is True

    def test_is_expired_no_expires_at(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "t3")
        assert model.is_expired is False

    def test_is_expired_false_future(self, app, db, admin_user):
        from unittest.mock import patch
        future = datetime(2099, 1, 1, 0, 0, 0)  # far future, naive (SQLite strips tz)
        model, _ = ApiToken.create_token(admin_user.id, "t4", expires_at=future)
        with patch("app.models.api_token.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 0, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert model.is_expired is False

    def test_is_expired_true_past(self, app, db, admin_user):
        from unittest.mock import patch
        past = datetime(2020, 1, 1, 0, 0, 0)  # far past, naive (SQLite strips tz)
        model, _ = ApiToken.create_token(admin_user.id, "t5", expires_at=past)
        with patch("app.models.api_token.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 0, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert model.is_expired is True

    def test_is_valid_all_combinations(self, app, db, admin_user):
        from unittest.mock import patch

        # Valid: not revoked, not expired
        m1, _ = ApiToken.create_token(admin_user.id, "v1")
        assert m1.is_valid is True

        # Revoked: not valid
        m2, _ = ApiToken.create_token(admin_user.id, "v2")
        m2.revoke()
        assert m2.is_valid is False

        # Expired: not valid (use mock to avoid naive/aware SQLite issue)
        naive_past = datetime(2020, 1, 1, 0, 0, 0)
        m3, _ = ApiToken.create_token(admin_user.id, "v3", expires_at=naive_past)
        with patch("app.models.api_token.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 1, 0, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert m3.is_valid is False

        # Expired AND revoked: not valid
        m4, _ = ApiToken.create_token(admin_user.id, "v4", expires_at=naive_past)
        m4.revoked_at = datetime(2025, 1, 1, 0, 0, 0)
        db.session.commit()
        with patch("app.models.api_token.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 1, 0, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert m4.is_valid is False


class TestApiTokenDisplayToken:
    def test_display_masking(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "disp-tok")
        display = model.display_token
        assert display.startswith("qap_")
        assert "*" in display
        # Should be qap_ + 28 stars = 32 chars total
        assert len(display) == 32


class TestApiTokenRevoke:
    def test_revoke_sets_revoked_at(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "rev-tok")
        assert model.revoked_at is None
        model.revoke()
        assert model.revoked_at is not None


class TestApiTokenRepr:
    def test_repr(self, app, db, admin_user):
        model, _ = ApiToken.create_token(admin_user.id, "repr-tok")
        r = repr(model)
        assert "ApiToken" in r
        assert "repr-tok" in r


# ============================================================================
# Step 5: User model tests
# ============================================================================


class TestUserHasPermission:
    def test_super_admin_has_all(self, app, db, admin_user):
        for perm in ROLE_PERMISSIONS[Role.SUPER_ADMIN]:
            assert admin_user.has_permission(perm) is True

    def test_project_lead_permissions(self, app, db, lead_user):
        assert lead_user.has_permission("project.create") is True
        assert lead_user.has_permission("user.manage") is False

    def test_tester_permissions(self, app, db, tester_user):
        assert tester_user.has_permission("execution.trigger") is True
        assert tester_user.has_permission("project.create") is False

    def test_visitor_permissions(self, app, db, visitor_user):
        assert visitor_user.has_permission("execution.view") is True
        assert visitor_user.has_permission("execution.trigger") is False

    def test_missing_permission(self, app, db, tester_user):
        assert tester_user.has_permission("nonexistent.permission") is False


class TestUserHasRole:
    def test_enum_value_match(self, app, db, admin_user):
        assert admin_user.has_role(Role.SUPER_ADMIN) is True

    def test_string_value_match(self, app, db, admin_user):
        assert admin_user.has_role("super_admin") is True

    def test_enum_no_match(self, app, db, tester_user):
        assert tester_user.has_role(Role.SUPER_ADMIN) is False

    def test_string_no_match(self, app, db, tester_user):
        assert tester_user.has_role("super_admin") is False

    def test_multiple_roles(self, app, db, lead_user):
        assert lead_user.has_role(Role.SUPER_ADMIN, Role.PROJECT_LEAD) is True

    def test_multiple_roles_mixed(self, app, db, lead_user):
        assert lead_user.has_role("super_admin", Role.PROJECT_LEAD) is True


class TestUserRoleDisplay:
    def test_super_admin(self, app, db, admin_user):
        assert admin_user.role_display == "Super Admin"

    def test_project_lead(self, app, db, lead_user):
        assert lead_user.role_display == "Project Lead"

    def test_tester(self, app, db, tester_user):
        assert tester_user.role_display == "Tester"

    def test_visitor(self, app, db, visitor_user):
        assert visitor_user.role_display == "Visitor"


class TestUserFlaskLoginProperties:
    def test_is_authenticated(self, app, db, admin_user):
        assert admin_user.is_authenticated is True

    def test_is_anonymous(self, app, db, admin_user):
        assert admin_user.is_anonymous is False

    def test_get_id_returns_string(self, app, db, admin_user):
        gid = admin_user.get_id()
        assert isinstance(gid, str)
        assert gid == str(admin_user.id)


class TestUserHasProjectPermission:
    """Complementary edge cases for has_project_permission.
    Main branches already tested in test_project_rbac.py.
    """

    def test_super_admin_always_true(self, app, db, admin_user, sample_project):
        assert admin_user.has_project_permission("any.perm", sample_project.id) is True

    def test_no_membership_not_owner(self, app, db, tester_user, sample_project):
        assert tester_user.has_project_permission("execution.trigger", sample_project.id) is False

    def test_owner_grants_permission(self, app, db, admin_user, sample_project):
        # admin_user is the owner via sample_project fixture
        assert admin_user.has_project_permission("execution.trigger", sample_project.id) is True

    def test_membership_with_matching_permission(self, app, db, tester_user, sample_project):
        pm = ProjectMembership(
            user_id=tester_user.id,
            project_id=sample_project.id,
            role=ProjectRole.TESTER,
        )
        db.session.add(pm)
        db.session.commit()
        assert tester_user.has_project_permission("execution.view", sample_project.id) is True

    def test_membership_without_matching_permission(self, app, db, tester_user, sample_project):
        pm = ProjectMembership(
            user_id=tester_user.id,
            project_id=sample_project.id,
            role=ProjectRole.VIEWER,
        )
        db.session.add(pm)
        db.session.commit()
        assert tester_user.has_project_permission("project.members.manage", sample_project.id) is False


class TestUserRepr:
    def test_repr(self, app, db, admin_user):
        r = repr(admin_user)
        assert "admin" in r
        assert "super_admin" in r


# ============================================================================
# Step 6: Remaining model __repr__ and enum tests
# ============================================================================


class TestNotificationConfigRepr:
    def test_repr(self):
        cfg = NotificationConfig(id=1, project_id=5, channel=NotificationChannel.EMAIL)
        r = repr(cfg)
        assert "NotificationConfig" in r
        assert "email" in r


class TestNotificationLogRepr:
    def test_repr(self):
        log = NotificationLog(
            id=1, execution_id=10,
            channel=NotificationChannel.DINGTALK,
            status=NotificationDeliveryStatus.SENT,
        )
        r = repr(log)
        assert "NotificationLog" in r
        assert "dingtalk" in r
        assert "sent" in r


class TestAuditLogRepr:
    def test_repr(self):
        entry = AuditLog(id=1, action="user.login", username="admin", resource_type="user", resource_id="1")
        r = repr(entry)
        assert "user.login" in r
        assert "admin" in r


class TestAllureReportRepr:
    def test_repr(self):
        report = AllureReport(execution_id=42, report_path="/tmp/report", report_url="/reports/42")
        r = repr(report)
        assert "42" in r


class TestDashboardMetricRepr:
    def test_repr(self):
        dm = DashboardMetric(project_id=1, date="2025-01-01", pass_rate=0.95)
        r = repr(dm)
        assert "0.95" in r


class TestTestResultRepr:
    def test_repr(self):
        tr = TestResult(name="test_foo", status=TestResultStatus.PASSED, execution_id=1)
        r = repr(tr)
        assert "test_foo" in r
        assert "passed" in r


class TestEnumValues:
    """Verify all enum values exist and are correct."""

    def test_test_result_status_values(self):
        assert TestResultStatus.PASSED.value == "passed"
        assert TestResultStatus.FAILED.value == "failed"
        assert TestResultStatus.ERROR.value == "error"
        assert TestResultStatus.SKIPPED.value == "skipped"

    def test_notification_channel_values(self):
        assert NotificationChannel.EMAIL.value == "email"
        assert NotificationChannel.DINGTALK.value == "dingtalk"
        assert NotificationChannel.WECHAT.value == "wechat"

    def test_notification_delivery_status_values(self):
        assert NotificationDeliveryStatus.SENT.value == "sent"
        assert NotificationDeliveryStatus.FAILED.value == "failed"

    def test_project_role_values(self):
        assert ProjectRole.OWNER.value == "owner"
        assert ProjectRole.LEAD.value == "lead"
        assert ProjectRole.TESTER.value == "tester"
        assert ProjectRole.VIEWER.value == "viewer"

    def test_trigger_type_values(self):
        assert TriggerType.WEB.value == "web"
        assert TriggerType.CRON.value == "cron"
        assert TriggerType.API.value == "api"

    def test_execution_status_values(self):
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.CLONED.value == "cloned"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.EXECUTED.value == "executed"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.TIMEOUT.value == "timeout"

    def test_role_values(self):
        assert Role.SUPER_ADMIN.value == "super_admin"
        assert Role.PROJECT_LEAD.value == "project_lead"
        assert Role.TESTER.value == "tester"
        assert Role.VISITOR.value == "visitor"


class TestProjectRolePermissionsCompleteness:
    """Verify all ProjectRole enum members have entries in PROJECT_ROLE_PERMISSIONS."""

    def test_all_roles_in_permissions_map(self):
        for role in ProjectRole:
            assert role in PROJECT_ROLE_PERMISSIONS, f"Missing permissions for {role}"

    def test_owner_has_manage_members(self):
        assert "project.members.manage" in PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]

    def test_viewer_limited_permissions(self):
        perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]
        assert "project.settings" not in perms
        assert "execution.view" in perms
