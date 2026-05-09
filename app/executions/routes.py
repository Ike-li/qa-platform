"""Execution routes: trigger, list, detail."""

import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.executions import executions_bp
from app.executions.forms import ExecutionTriggerForm
from app.executions.services import prepare_execution
from app.extensions import db
from app.models.execution import Execution, ExecutionStatus, TriggerType
from app.models.project import Project
from app.models.test_result import TestResult, TestResultStatus
from app.models.test_suite import TestSuite
from app.utils.audit import log_audit

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# List executions (paginated)
# ------------------------------------------------------------------

@executions_bp.route("/")
@login_required
def list_executions():
    if not current_user.has_permission("execution.view"):
        abort(403)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    project_id = request.args.get("project_id", type=int)
    status_filter = request.args.get("status", "").strip()

    query = Execution.query
    if project_id:
        query = query.filter_by(project_id=project_id)
    if status_filter:
        try:
            query = query.filter_by(status=ExecutionStatus(status_filter))
        except ValueError:
            pass

    pagination = query.order_by(Execution.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )

    projects = Project.query.order_by(Project.name).all()

    return render_template(
        "executions/list.html",
        pagination=pagination,
        executions=pagination.items,
        projects=projects,
        project_id=project_id,
        status_filter=status_filter,
    )


# ------------------------------------------------------------------
# Detail (with stage indicator, results, report link)
# ------------------------------------------------------------------

@executions_bp.route("/<int:id>")
@login_required
def detail_execution(id: int):
    if not current_user.has_permission("execution.view"):
        abort(403)

    execution = Execution.query.get_or_404(id)

    results = (
        execution.results
        .order_by(TestResult.status, TestResult.name)
        .all()
    )

    # Compute summary counts
    counts = {s: 0 for s in TestResultStatus}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    return render_template(
        "executions/detail.html",
        execution=execution,
        results=results,
        counts=counts,
    )


# ------------------------------------------------------------------
# Trigger a new execution
# ------------------------------------------------------------------

@executions_bp.route("/trigger/<int:project_id>", methods=["GET", "POST"])
@login_required
def trigger_execution(project_id: int):
    if not current_user.has_permission("execution.trigger"):
        abort(403)

    project = Project.query.get_or_404(project_id)
    suites = project.suites.order_by(TestSuite.name).all()

    form = ExecutionTriggerForm()
    form.suite_id.choices = [(0, "-- All Suites --")] + [
        (s.id, f"{s.name} ({s.path_in_repo})") for s in suites
    ]

    if form.validate_on_submit():
        suite_id = form.suite_id.data or None  # 0 means all
        extra_args = form.extra_args.data or None

        try:
            execution = prepare_execution(
                project_id=project.id,
                suite_id=suite_id,
                extra_args=extra_args,
                trigger_type=TriggerType.WEB,
            )

            # Dispatch the chained Celery pipeline
            from app.tasks.execution_tasks import run_execution_pipeline

            result = run_execution_pipeline.delay(execution.id)
            execution.celery_task_id = result.id
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise

            log_audit(
                "execution.trigger",
                resource_type="execution",
                resource_id=execution.id,
                new_value={
                    "project_id": project.id,
                    "suite_id": suite_id,
                    "extra_args": extra_args,
                },
            )

            flash(f"Execution #{execution.id} queued successfully.", "success")
            return redirect(url_for("executions.detail_execution", id=execution.id))

        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            logger.exception("Failed to trigger execution")
            flash(f"Failed to trigger execution: {exc}", "danger")

    return render_template(
        "executions/trigger.html",
        form=form,
        project=project,
        suites=suites,
    )
