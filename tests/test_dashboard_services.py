"""Tests for app/dashboard/services.py – direct service-layer tests."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch


from app.dashboard.services import (
    aggregate_daily_metrics,
    get_all_projects_health,
    get_global_overview,
    get_pass_rate_data,
    get_queue_status,
    get_recent_failures,
    get_trend_data,
)
from app.models.dashboard_metric import DashboardMetric
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.project import Project
from app.models.test_result import TestResult, TestResultStatus
from app.models.test_suite import TestSuite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_execution(
    db,
    project,
    status=ExecutionStatus.COMPLETED,
    started_at=None,
    finished_at=None,
    suite=None,
    trigger_type=TriggerType.WEB,
    created_at=None,
):
    ex = Execution(
        project_id=project.id,
        suite_id=suite.id if suite else None,
        status=status,
        trigger_type=trigger_type,
        started_at=started_at,
        finished_at=finished_at,
        created_at=created_at or datetime(2026, 5, 10, 12, 0, 0),
    )
    db.session.add(ex)
    db.session.commit()
    return ex


def _create_test_result(
    db,
    execution,
    name,
    status=TestResultStatus.PASSED,
    duration=1.0,
    error_msg=None,
    file_path="test_foo.py",
):
    tr = TestResult(
        execution_id=execution.id,
        name=name,
        status=status,
        duration_sec=duration,
        error_msg=error_msg,
        file_path=file_path,
    )
    db.session.add(tr)
    db.session.commit()
    return tr


def _create_metric(
    db,
    project,
    d,
    pass_count,
    fail_count,
    skip_count,
    error_count,
    pass_rate,
    total_runs=None,
):
    m = DashboardMetric(
        project_id=project.id,
        date=d,
        pass_count=pass_count,
        fail_count=fail_count,
        skip_count=skip_count,
        error_count=error_count,
        total_runs=total_runs
        if total_runs is not None
        else pass_count + fail_count + skip_count + error_count,
        pass_rate=pass_rate,
    )
    db.session.add(m)
    db.session.commit()
    return m


FIXED_DATE = date(2026, 5, 10)
FIXED_DT = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# TestGetPassRateData
# ===========================================================================


class TestGetPassRateData:
    @patch("app.dashboard.services.date")
    def test_with_dashboard_metric_rows(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        _create_metric(
            db,
            sample_project,
            FIXED_DATE - timedelta(days=1),
            8,
            2,
            0,
            0,
            80.0,
            total_runs=10,
        )
        _create_metric(db, sample_project, FIXED_DATE, 9, 0, 1, 0, 90.0, total_runs=10)

        result = get_pass_rate_data(sample_project.id, days=7)
        assert result["total_tests"] == 20
        assert result["pass_rate"] == 85.0
        assert result["counts"]["passed"] == 17
        assert result["counts"]["failed"] == 2
        assert result["counts"]["skipped"] == 1
        assert result["counts"]["error"] == 0

    @patch("app.dashboard.services.date")
    def test_fallback_path_no_metrics(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        ex = _create_execution(
            db,
            sample_project,
            status=ExecutionStatus.COMPLETED,
            created_at=datetime(2026, 5, 8, 10, 0, 0),
            finished_at=datetime(2026, 5, 8, 11, 0, 0),
        )
        for _ in range(5):
            _create_test_result(db, ex, f"pass_{_}", TestResultStatus.PASSED)
        for _ in range(3):
            _create_test_result(db, ex, f"fail_{_}", TestResultStatus.FAILED)

        result = get_pass_rate_data(sample_project.id, days=7)
        assert result["total_tests"] == 8
        assert result["pass_rate"] == 62.5
        assert result["counts"]["passed"] == 5
        assert result["counts"]["failed"] == 3

    @patch("app.dashboard.services.date")
    def test_no_data_at_all(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        result = get_pass_rate_data(sample_project.id, days=7)
        assert result["total_tests"] == 0
        assert result["pass_rate"] == 0.0
        assert result["counts"]["passed"] == 0
        assert result["counts"]["failed"] == 0

    @patch("app.dashboard.services.date")
    def test_custom_days_parameter(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        # Create metrics for 10 days, only last 5 should be included
        for i in range(10):
            d = FIXED_DATE - timedelta(days=9 - i)
            _create_metric(db, sample_project, d, 1, 0, 0, 0, 100.0, total_runs=1)

        result = get_pass_rate_data(sample_project.id, days=5)
        assert result["total_tests"] == 5  # only 5 days worth


# ===========================================================================
# TestGetTrendData
# ===========================================================================


class TestGetTrendData:
    @patch("app.dashboard.services.date")
    def test_daily_granularity(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        for i, (d, pr) in enumerate(
            [
                (date(2026, 5, 8), 80.0),
                (date(2026, 5, 9), 90.0),
                (date(2026, 5, 10), 100.0),
            ]
        ):
            _create_metric(db, sample_project, d, 8, 2, 0, 0, pr, total_runs=10)

        result = get_trend_data(sample_project.id, granularity="daily", days=7)
        assert result["labels"] == ["2026-05-08", "2026-05-09", "2026-05-10"]
        assert result["pass_rates"] == [80.0, 90.0, 100.0]

    @patch("app.dashboard.services.date")
    def test_weekly_granularity(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        # April 28 = ISO week 18; May 5, May 8 = ISO week 19
        _create_metric(
            db, sample_project, date(2026, 4, 28), 5, 5, 0, 0, 50.0, total_runs=10
        )
        _create_metric(
            db, sample_project, date(2026, 5, 5), 8, 2, 0, 0, 80.0, total_runs=10
        )
        _create_metric(
            db, sample_project, date(2026, 5, 8), 9, 1, 0, 0, 90.0, total_runs=10
        )

        result = get_trend_data(sample_project.id, granularity="weekly", days=3)
        # Week 18: 50.0, Week 19: avg(80.0, 90.0) = 85.0
        assert "2026-W18" in result["labels"]
        assert "2026-W19" in result["labels"]
        idx18 = result["labels"].index("2026-W18")
        idx19 = result["labels"].index("2026-W19")
        assert result["pass_rates"][idx18] == 50.0
        assert result["pass_rates"][idx19] == 85.0

    @patch("app.dashboard.services.date")
    def test_monthly_granularity(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        _create_metric(
            db, sample_project, date(2026, 4, 15), 6, 4, 0, 0, 60.0, total_runs=10
        )
        _create_metric(
            db, sample_project, date(2026, 5, 5), 9, 1, 0, 0, 90.0, total_runs=10
        )

        result = get_trend_data(sample_project.id, granularity="monthly", days=2)
        assert result["labels"] == ["2026-04", "2026-05"]
        assert result["pass_rates"] == [60.0, 90.0]

    @patch("app.dashboard.services.date")
    def test_empty_data(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        result = get_trend_data(sample_project.id, granularity="daily", days=7)
        assert result["labels"] == []
        assert result["pass_rates"] == []


# ===========================================================================
# TestGetQueueStatus
# ===========================================================================


class TestGetQueueStatus:
    # All queue tests mock datetime to avoid tz-aware/naive mismatch with SQLite.
    # SQLite strips timezone info, so created_at/stored datetimes are naive.
    # datetime.now(timezone.utc) is aware; patch to return naive to match.

    @patch("app.dashboard.services.datetime")
    def test_basic_queue(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        suite = TestSuite(
            name="Regression",
            project_id=sample_project.id,
            path_in_repo="tests/regression.py",
        )
        db.session.add(suite)
        db.session.commit()

        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.RUNNING,
            started_at=datetime(2026, 5, 10, 11, 30, 0),
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.EXECUTED,
            started_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 11, 0, 0),
            suite=suite,
        )

        result = get_queue_status()
        assert len(result) == 3
        statuses = {r["status"] for r in result}
        assert statuses == {"pending", "running", "executed"}
        exec_with_suite = [r for r in result if r["status"] == "executed"][0]
        assert exec_with_suite["suite_name"] == "Regression"

    @patch("app.dashboard.services.datetime")
    def test_elapsed_with_started_at(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        _create_execution(
            db,
            sample_project,
            ExecutionStatus.RUNNING,
            started_at=datetime(2026, 5, 10, 11, 59, 0),
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )

        result = get_queue_status()
        assert len(result) == 1
        assert result[0]["elapsed_seconds"] == 60.0

    @patch("app.dashboard.services.datetime")
    def test_elapsed_with_created_at_fallback(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 59, 30),
        )

        result = get_queue_status()
        assert len(result) == 1
        assert result[0]["elapsed_seconds"] == 30.0

    @patch("app.dashboard.services.datetime")
    def test_empty_queue(self, mock_dt, app, db):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)
        result = get_queue_status()
        assert result == []

    @patch("app.dashboard.services.datetime")
    def test_no_suite(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        result = get_queue_status()
        assert result[0]["suite_name"] == "All Suites"

    @patch("app.dashboard.services.datetime")
    def test_project_name(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        result = get_queue_status()
        assert result[0]["project_name"] == sample_project.name

    @patch("app.dashboard.services.datetime")
    def test_detail_url_and_trigger_type(self, mock_dt, app, db, sample_project):
        mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, 0)

        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            trigger_type=TriggerType.CRON,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        result = get_queue_status()
        assert result[0]["detail_url"] == f"/executions/{ex.id}"
        assert result[0]["trigger_type"] == "cron"


# ===========================================================================
# TestGetRecentFailures
# ===========================================================================


class TestGetRecentFailures:
    def test_basic_failures(self, app, db, sample_project):
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )
        _create_test_result(
            db,
            ex,
            "test_fail",
            TestResultStatus.FAILED,
            error_msg="assertion failed",
            duration=2.5,
        )
        _create_test_result(
            db,
            ex,
            "test_error",
            TestResultStatus.ERROR,
            error_msg="connection error",
            duration=0.5,
        )
        # A passing result should NOT appear
        _create_test_result(db, ex, "test_pass", TestResultStatus.PASSED)

        result = get_recent_failures(sample_project.id)
        assert len(result) == 2
        for r in result:
            assert r["status"] in ("failed", "error")
            assert r["execution_url"] == f"/executions/{ex.id}"
            assert "error_msg" in r
            assert "duration_sec" in r

    def test_error_truncation(self, app, db, sample_project):
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )
        long_msg = "x" * 250
        _create_test_result(
            db, ex, "test_trunc", TestResultStatus.FAILED, error_msg=long_msg
        )

        result = get_recent_failures(sample_project.id)
        assert len(result) == 1
        assert result[0]["error_msg"] == long_msg[:200]
        assert len(result[0]["error_msg"]) == 200

    def test_allure_url_present(self, app, db, sample_project):
        from app.models.allure_report import AllureReport

        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )
        report = AllureReport(
            execution_id=ex.id,
            report_path="/tmp/report",
            report_url="https://allure.example.com/report/1",
        )
        db.session.add(report)
        db.session.commit()
        _create_test_result(db, ex, "test_fail", TestResultStatus.FAILED)

        result = get_recent_failures(sample_project.id)
        assert result[0]["allure_url"] == "https://allure.example.com/report/1"

    def test_allure_url_absent(self, app, db, sample_project):
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )
        _create_test_result(db, ex, "test_fail", TestResultStatus.FAILED)

        result = get_recent_failures(sample_project.id)
        assert result[0]["allure_url"] is None

    def test_no_failures(self, app, db, sample_project):
        result = get_recent_failures(sample_project.id)
        assert result == []

    def test_executed_at_from_finished_at(self, app, db, sample_project):
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )
        _create_test_result(db, ex, "test_fail", TestResultStatus.FAILED)
        result = get_recent_failures(sample_project.id)
        assert result[0]["executed_at"] == "2026-05-10T11:00:00"


# ===========================================================================
# TestGetGlobalOverview
# ===========================================================================


class TestGetGlobalOverview:
    @patch("app.dashboard.services.date")
    def test_with_metrics(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        project2 = Project(
            name="Project B",
            description="Second",
            git_url="x",
            git_branch="main",
            owner_id=sample_project.owner_id,
        )
        db.session.add(project2)
        db.session.commit()

        _create_metric(db, sample_project, FIXED_DATE, 9, 1, 0, 0, 90.0, total_runs=10)
        _create_metric(db, project2, FIXED_DATE, 5, 5, 0, 0, 50.0, total_runs=10)

        # Active executions
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.RUNNING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
            started_at=datetime(2026, 5, 10, 11, 30, 0),
        )

        result = get_global_overview()
        assert result["total_projects"] == 2
        assert result["active_executions"] == 2
        # Weighted: 14 pass / 20 total = 70.0
        assert result["recent_pass_rate"] == 70.0
        assert project2.id in result["projects_with_failing_trends"]
        assert sample_project.id not in result["projects_with_failing_trends"]

    @patch("app.dashboard.services.date")
    def test_fallback_path(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            created_at=datetime(2026, 5, 8, 10, 0, 0),
            finished_at=datetime(2026, 5, 8, 11, 0, 0),
        )
        for _ in range(8):
            _create_test_result(db, ex, f"pass_{_}", TestResultStatus.PASSED)
        for _ in range(2):
            _create_test_result(db, ex, f"fail_{_}", TestResultStatus.FAILED)

        result = get_global_overview()
        assert result["total_projects"] == 1
        assert result["recent_pass_rate"] == 80.0

    @patch("app.dashboard.services.date")
    def test_no_data(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        result = get_global_overview()
        assert result["total_projects"] == 1  # sample_project exists
        assert result["active_executions"] == 0
        assert result["recent_pass_rate"] == 0.0
        assert result["projects_with_failing_trends"] == []

    @patch("app.dashboard.services.date")
    def test_only_active_statuses_counted(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.PENDING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.RUNNING,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
            finished_at=datetime(2026, 5, 10, 12, 0, 0),
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.FAILED,
            created_at=datetime(2026, 5, 10, 11, 0, 0),
        )

        result = get_global_overview()
        assert result["active_executions"] == 2  # only PENDING + RUNNING

    @patch("app.dashboard.services.date")
    def test_project_above_80_not_failing(self, mock_date, app, db, sample_project):
        mock_date.today.return_value = FIXED_DATE
        _create_metric(db, sample_project, FIXED_DATE, 9, 1, 0, 0, 90.0, total_runs=10)

        result = get_global_overview()
        assert sample_project.id not in result["projects_with_failing_trends"]


# ===========================================================================
# TestGetAllProjectsHealth
# ===========================================================================


class TestGetAllProjectsHealth:
    def test_projects_sorted_by_name(self, app, db, admin_user):
        p_b = Project(
            name="Beta",
            description="",
            git_url="x",
            git_branch="main",
            owner_id=admin_user.id,
        )
        p_a = Project(
            name="Alpha",
            description="",
            git_url="x",
            git_branch="main",
            owner_id=admin_user.id,
        )
        db.session.add_all([p_b, p_a])
        db.session.commit()

        result = get_all_projects_health()
        assert len(result) == 2
        assert result[0]["name"] == "Alpha"
        assert result[1]["name"] == "Beta"

    def test_project_with_metrics_and_execution(self, app, db, sample_project):
        _create_metric(
            db, sample_project, date(2026, 5, 9), 8, 2, 0, 0, 80.0, total_runs=10
        )
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 10, 0, 0),
            created_at=datetime(2026, 5, 10, 9, 0, 0),
        )

        result = get_all_projects_health()
        assert len(result) == 1
        assert result[0]["latest_pass_rate"] == 80.0
        assert result[0]["last_execution_at"] == "2026-05-10T10:00:00"
        assert result[0]["last_execution_status"] == "completed"

    def test_project_no_metrics_no_executions(self, app, db, sample_project):
        result = get_all_projects_health()
        assert len(result) == 1
        assert result[0]["latest_pass_rate"] is None
        assert result[0]["last_execution_at"] is None
        assert result[0]["last_execution_status"] is None

    def test_execution_with_no_finished_at(self, app, db, sample_project):
        _create_execution(
            db,
            sample_project,
            ExecutionStatus.RUNNING,
            started_at=datetime(2026, 5, 10, 11, 0, 0),
            created_at=datetime(2026, 5, 10, 10, 0, 0),
        )

        result = get_all_projects_health()
        assert result[0]["last_execution_at"] is None
        assert result[0]["last_execution_status"] == "running"


# ===========================================================================
# TestAggregateDailyMetrics
# ===========================================================================


class TestAggregateDailyMetrics:
    def test_create_new_metric(self, app, db, sample_project):
        target = date(2026, 5, 10)
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 10, 0, 0),
            created_at=datetime(2026, 5, 10, 9, 0, 0),
        )
        _create_test_result(db, ex, "t1", TestResultStatus.PASSED, duration=1.0)
        _create_test_result(db, ex, "t2", TestResultStatus.PASSED, duration=2.0)
        _create_test_result(db, ex, "t3", TestResultStatus.FAILED, duration=0.5)
        _create_test_result(db, ex, "t4", TestResultStatus.SKIPPED, duration=0.0)
        _create_test_result(db, ex, "t5", TestResultStatus.ERROR, duration=0.1)

        metric = aggregate_daily_metrics(sample_project.id, target)
        assert metric.total_runs == 5
        assert metric.pass_count == 2
        assert metric.fail_count == 1
        assert metric.skip_count == 1
        assert metric.error_count == 1
        assert metric.pass_rate == 40.0
        assert metric.avg_duration is not None

    def test_upsert_updates_existing(self, app, db, sample_project):
        target = date(2026, 5, 10)
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 10, 0, 0),
            created_at=datetime(2026, 5, 10, 9, 0, 0),
        )
        _create_test_result(db, ex, "t1", TestResultStatus.PASSED, duration=1.0)

        aggregate_daily_metrics(sample_project.id, target)

        # Add more results
        _create_test_result(db, ex, "t2", TestResultStatus.FAILED, duration=2.0)
        aggregate_daily_metrics(sample_project.id, target)

        count = DashboardMetric.query.filter_by(
            project_id=sample_project.id, date=target
        ).count()
        assert count == 1

    def test_no_executions(self, app, db, sample_project):
        target = date(2026, 5, 10)
        metric = aggregate_daily_metrics(sample_project.id, target)
        assert metric.total_runs == 0
        assert metric.pass_rate == 0.0

    def test_returned_object_matches_db(self, app, db, sample_project):
        target = date(2026, 5, 10)
        ex = _create_execution(
            db,
            sample_project,
            ExecutionStatus.COMPLETED,
            finished_at=datetime(2026, 5, 10, 10, 0, 0),
            created_at=datetime(2026, 5, 10, 9, 0, 0),
        )
        _create_test_result(db, ex, "t1", TestResultStatus.PASSED, duration=1.5)

        metric = aggregate_daily_metrics(sample_project.id, target)
        db_metric = DashboardMetric.query.filter_by(
            project_id=sample_project.id, date=target
        ).first()
        assert db_metric is not None
        assert metric.pass_count == db_metric.pass_count
        assert metric.pass_rate == db_metric.pass_rate
