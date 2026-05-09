"""Admin services – config validation and data retention enforcement."""

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.execution import Execution
from app.models.allure_report import AllureReport
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

_VALIDATION_RULES: dict[str, dict] = {
    "execution.timeout_minutes": {"type": "int", "min": 1, "max": 1440},
    "execution.git_timeout_minutes": {"type": "int", "min": 1, "max": 120},
    "execution.report_timeout_minutes": {"type": "int", "min": 1, "max": 120},
    "execution.max_parallel": {"type": "int", "min": 1, "max": 20},
    "retention.execution_days": {"type": "int", "min": 1, "max": 3650},
    "retention.report_days": {"type": "int", "min": 1, "max": 3650},
    "retention.audit_days": {"type": "int", "min": 1, "max": 3650},
    "notification.smtp_port": {"type": "int", "min": 1, "max": 65535},
}


def validate_config_value(key: str, raw_value: str) -> tuple[bool, str]:
    """Validate a config value against its rules.

    Parameters
    ----------
    key : str
        The SystemConfig key.
    raw_value : str
        The raw string value from the form.

    Returns
    -------
    (is_valid, error_message) – error_message is empty on success.
    """
    rules = _VALIDATION_RULES.get(key)
    if rules is None:
        return True, ""

    if rules["type"] == "int":
        try:
            val = int(raw_value)
        except (ValueError, TypeError):
            return False, f"'{key}' must be an integer."
        if val < rules.get("min", 0):
            return False, f"'{key}' must be >= {rules['min']}."
        if val > rules.get("max", float("inf")):
            return False, f"'{key}' must be <= {rules['max']}."

    return True, ""


def validate_all_configs(form_data: dict[str, str]) -> tuple[bool, dict[str, str]]:
    """Validate every submitted config value.

    Parameters
    ----------
    form_data : dict
        ``{config_key: raw_value}`` from the form.

    Returns
    -------
    (all_valid, errors_dict) – ``errors_dict`` maps key -> error message.
    """
    errors: dict[str, str] = {}
    for key, raw_value in form_data.items():
        ok, msg = validate_config_value(key, raw_value)
        if not ok:
            errors[key] = msg
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Retention enforcement
# ---------------------------------------------------------------------------


def enforce_retention() -> dict[str, int]:
    """Delete expired executions, reports, and audit logs based on SystemConfig.

    Returns
    -------
    dict with keys ``executions_deleted``, ``reports_deleted``, ``audit_deleted``
    indicating how many rows were removed.
    """
    now = datetime.now(timezone.utc)
    result = {"executions_deleted": 0, "reports_deleted": 0, "audit_deleted": 0}

    # --- Executions ---
    exec_days = SystemConfig.get("retention.execution_days", 90)
    if exec_days and exec_days > 0:
        cutoff = now - timedelta(days=int(exec_days))
        old_execs = Execution.query.filter(Execution.created_at < cutoff).all()
        if old_execs:
            exec_ids = [e.id for e in old_execs]
            # Delete related reports first (files + rows)
            old_reports = AllureReport.query.filter(
                AllureReport.execution_id.in_(exec_ids)
            ).all()
            for rpt in old_reports:
                _delete_report_files(rpt.report_path)
                db.session.delete(rpt)

            # Delete executions (cascade removes test_results too)
            for exe in old_execs:
                db.session.delete(exe)
            db.session.commit()
            result["executions_deleted"] = len(old_execs)
            logger.info("Retention: deleted %d executions before %s", len(old_execs), cutoff.date())

    # --- Reports (standalone cleanup for reports that outlive their retention) ---
    rpt_days = SystemConfig.get("retention.report_days", 30)
    if rpt_days and rpt_days > 0:
        cutoff = now - timedelta(days=int(rpt_days))
        old_reports = AllureReport.query.filter(AllureReport.generated_at < cutoff).all()
        if old_reports:
            for rpt in old_reports:
                _delete_report_files(rpt.report_path)
                db.session.delete(rpt)
            db.session.commit()
            result["reports_deleted"] = len(old_reports)
            logger.info("Retention: deleted %d reports before %s", len(old_reports), cutoff.date())

    # --- Audit logs ---
    audit_days = SystemConfig.get("retention.audit_days", 180)
    if audit_days and audit_days > 0:
        cutoff = now - timedelta(days=int(audit_days))
        count = AuditLog.query.filter(AuditLog.created_at < cutoff).delete()
        db.session.commit()
        result["audit_deleted"] = count
        if count:
            logger.info("Retention: deleted %d audit logs before %s", count, cutoff.date())

    return result


def _delete_report_files(report_path: str) -> None:
    """Remove Allure report directory from disk, ignoring errors."""
    try:
        if report_path and os.path.isdir(report_path):
            shutil.rmtree(report_path)
            logger.debug("Removed report directory: %s", report_path)
    except OSError as exc:
        logger.warning("Failed to remove report directory %s: %s", report_path, exc)
