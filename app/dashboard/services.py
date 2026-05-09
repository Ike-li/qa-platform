"""Dashboard data aggregation services.

Provides functions to compute pass-rate data, trend data, queue status,
recent failures, and to persist daily DashboardMetric rows.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from app.extensions import db
from app.models.dashboard_metric import DashboardMetric
from app.models.execution import Execution, ExecutionStatus
from app.models.project import Project
from app.models.test_result import TestResult, TestResultStatus

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Pass-rate aggregation (for doughnut chart)
# ------------------------------------------------------------------

def get_pass_rate_data(project_id: int, days: int = 7) -> dict:
    """Return aggregated pass/fail/skip/error counts over *days* days.

    Uses pre-aggregated DashboardMetric rows when available; falls back
    to querying TestResult directly for the current day (not yet aggregated).
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    rows = (
        DashboardMetric.query
        .filter(
            DashboardMetric.project_id == project_id,
            DashboardMetric.date >= start_date,
            DashboardMetric.date <= end_date,
        )
        .all()
    )

    if rows:
        total_pass = sum(r.pass_count for r in rows)
        total_fail = sum(r.fail_count for r in rows)
        total_skip = sum(r.skip_count for r in rows)
        total_error = sum(r.error_count for r in rows)
    else:
        # Fallback: aggregate from test_results directly
        start_dt = datetime.combine(start_date, datetime.min.time())
        counts = (
            db.session.query(
                TestResult.status,
                func.count(TestResult.id),
            )
            .join(Execution, Execution.id == TestResult.execution_id)
            .filter(
                Execution.project_id == project_id,
                Execution.created_at >= start_dt,
                Execution.status == ExecutionStatus.COMPLETED,
            )
            .group_by(TestResult.status)
            .all()
        )
        count_map = {status.value: cnt for status, cnt in counts}
        total_pass = count_map.get("passed", 0)
        total_fail = count_map.get("failed", 0)
        total_skip = count_map.get("skipped", 0)
        total_error = count_map.get("error", 0)

    grand_total = total_pass + total_fail + total_skip + total_error
    pass_rate = round(total_pass / grand_total * 100, 1) if grand_total > 0 else 0.0

    return {
        "pass_rate": pass_rate,
        "total_tests": grand_total,
        "counts": {
            "passed": total_pass,
            "failed": total_fail,
            "skipped": total_skip,
            "error": total_error,
        },
    }


# ------------------------------------------------------------------
# Trend data (for line chart)
# ------------------------------------------------------------------

def get_trend_data(
    project_id: int,
    granularity: str = "daily",
    days: int = 30,
) -> dict:
    """Return daily/weekly/monthly pass-rate trend data.

    Returns a dict with ``labels`` (ISO date strings) and ``pass_rates``
    (float 0-100) suitable for Chart.js line chart consumption.
    """
    end_date = date.today()
    if granularity == "weekly":
        lookback = days * 7  # approximate
    elif granularity == "monthly":
        lookback = days * 30
    else:
        lookback = days
    start_date = end_date - timedelta(days=lookback - 1)

    rows = (
        DashboardMetric.query
        .filter(
            DashboardMetric.project_id == project_id,
            DashboardMetric.date >= start_date,
            DashboardMetric.date <= end_date,
        )
        .order_by(DashboardMetric.date.asc())
        .all()
    )

    # Group by granularity
    bucket: dict[str, list[float]] = {}
    for r in rows:
        if granularity == "weekly":
            # ISO week key
            iso = r.date.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        elif granularity == "monthly":
            key = r.date.strftime("%Y-%m")
        else:
            key = r.date.isoformat()

        if key not in bucket:
            bucket[key] = []
        bucket[key].append(r.pass_rate)

    labels = sorted(bucket.keys())
    pass_rates = [round(sum(bucket[k]) / len(bucket[k]), 1) for k in labels]

    return {
        "labels": labels,
        "pass_rates": pass_rates,
    }


# ------------------------------------------------------------------
# Queue status (live)
# ------------------------------------------------------------------

def get_queue_status() -> list[dict]:
    """Return running and pending executions with elapsed time info."""
    now = datetime.now(timezone.utc)

    executions = (
        Execution.query
        .filter(
            Execution.status.in_([
                ExecutionStatus.PENDING,
                ExecutionStatus.CLONED,
                ExecutionStatus.RUNNING,
                ExecutionStatus.EXECUTED,
            ])
        )
        .order_by(Execution.created_at.asc())
        .all()
    )

    queue = []
    for ex in executions:
        elapsed = None
        if ex.started_at:
            delta = now - ex.started_at
            elapsed = round(delta.total_seconds(), 0)
        elif ex.created_at:
            delta = now - ex.created_at
            elapsed = round(delta.total_seconds(), 0)

        project_name = ex.project.name if ex.project else "Unknown"
        suite_name = ex.suite.name if ex.suite else "All Suites"

        queue.append({
            "id": ex.id,
            "project_id": ex.project_id,
            "project_name": project_name,
            "suite_name": suite_name,
            "status": ex.status.value,
            "stage": ex.stage_indicator,
            "trigger_type": ex.trigger_type.value,
            "elapsed_seconds": elapsed,
            "created_at": ex.created_at.isoformat() if ex.created_at else None,
            "detail_url": f"/executions/{ex.id}",
        })

    return queue


# ------------------------------------------------------------------
# Recent failures (with Allure links)
# ------------------------------------------------------------------

def get_recent_failures(project_id: int, limit: int = 20) -> list[dict]:
    """Return recent failed/error test results with Allure report links."""
    results = (
        db.session.query(TestResult, Execution)
        .join(Execution, Execution.id == TestResult.execution_id)
        .filter(
            Execution.project_id == project_id,
            Execution.status == ExecutionStatus.COMPLETED,
            TestResult.status.in_([
                TestResultStatus.FAILED,
                TestResultStatus.ERROR,
            ]),
        )
        .order_by(Execution.finished_at.desc())
        .limit(limit)
        .all()
    )

    failures = []
    for tr, ex in results:
        # Allure report link
        allure_url = None
        if ex.allure_report:
            allure_url = ex.allure_report.report_url

        failures.append({
            "id": tr.id,
            "execution_id": ex.id,
            "test_name": tr.name,
            "file_path": tr.file_path,
            "status": tr.status.value,
            "error_msg": (tr.error_msg[:200] if tr.error_msg else None),
            "duration_sec": tr.duration_sec,
            "executed_at": ex.finished_at.isoformat() if ex.finished_at else None,
            "allure_url": allure_url,
            "execution_url": f"/executions/{ex.id}",
        })

    return failures


# ------------------------------------------------------------------
# Daily metric aggregation (for Celery Beat)
# ------------------------------------------------------------------

def aggregate_daily_metrics(project_id: int, target_date: date) -> DashboardMetric:
    """Compute and upsert a DashboardMetric row for one project + date.

    Counts all test results from executions that completed on *target_date*.
    """
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    # Aggregate counts from completed executions on that date
    row = (
        db.session.query(
            func.count(TestResult.id).label("total"),
            func.sum(
                func.cast(TestResult.status == TestResultStatus.PASSED, db.Integer)
            ).label("pass_count"),
            func.sum(
                func.cast(TestResult.status == TestResultStatus.FAILED, db.Integer)
            ).label("fail_count"),
            func.sum(
                func.cast(TestResult.status == TestResultStatus.SKIPPED, db.Integer)
            ).label("skip_count"),
            func.sum(
                func.cast(TestResult.status == TestResultStatus.ERROR, db.Integer)
            ).label("error_count"),
            func.avg(TestResult.duration_sec).label("avg_duration"),
        )
        .join(Execution, Execution.id == TestResult.execution_id)
        .filter(
            Execution.project_id == project_id,
            Execution.status == ExecutionStatus.COMPLETED,
            Execution.finished_at >= start_dt,
            Execution.finished_at < end_dt,
        )
        .one()
    )

    total = row.total or 0
    pass_count = row.pass_count or 0
    fail_count = row.fail_count or 0
    skip_count = row.skip_count or 0
    error_count = row.error_count or 0
    avg_duration = round(float(row.avg_duration), 2) if row.avg_duration else None
    pass_rate = round(pass_count / total * 100, 2) if total > 0 else 0.0

    # Upsert: update existing or create new
    metric = DashboardMetric.query.filter_by(
        project_id=project_id,
        date=target_date,
    ).first()

    if metric:
        metric.total_runs = total
        metric.pass_count = pass_count
        metric.fail_count = fail_count
        metric.skip_count = skip_count
        metric.error_count = error_count
        metric.pass_rate = pass_rate
        metric.avg_duration = avg_duration
    else:
        metric = DashboardMetric(
            project_id=project_id,
            date=target_date,
            total_runs=total,
            pass_count=pass_count,
            fail_count=fail_count,
            skip_count=skip_count,
            error_count=error_count,
            pass_rate=pass_rate,
            avg_duration=avg_duration,
        )
        db.session.add(metric)

    db.session.commit()
    logger.info(
        "DashboardMetric upserted: project=%d date=%s pass_rate=%.1f%%",
        project_id, target_date, pass_rate,
    )
    return metric
