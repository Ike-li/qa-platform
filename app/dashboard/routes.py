"""Dashboard routes: main page and JSON API endpoints."""

from flask import jsonify, render_template, request
from flask_login import login_required

from app.dashboard import dashboard_bp
from app.dashboard.services import (
    get_all_projects_health,
    get_global_overview,
    get_pass_rate_data,
    get_queue_status,
    get_recent_failures,
    get_trend_data,
)
from app.models.project import Project


# ------------------------------------------------------------------
# Main dashboard page
# ------------------------------------------------------------------

@dashboard_bp.route("/")
@login_required
def index():
    """Render the main dashboard page."""
    projects = Project.query.order_by(Project.name).all()
    return render_template("dashboard/index.html", projects=projects)


# ------------------------------------------------------------------
# JSON API: Pass rate (doughnut chart)
# ------------------------------------------------------------------

@dashboard_bp.route("/api/dashboard/pass-rate")
@login_required
def api_pass_rate():
    """Return aggregated pass/fail/skip/error data for doughnut chart.

    Query params: project_id (required), days (default 7).
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 365))

    data = get_pass_rate_data(project_id, days)
    return jsonify(data)


# ------------------------------------------------------------------
# JSON API: Trends (line chart)
# ------------------------------------------------------------------

@dashboard_bp.route("/api/dashboard/trends")
@login_required
def api_trends():
    """Return trend data for line chart.

    Query params: project_id (required), granularity (daily|weekly|monthly),
    days (default 30).
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    granularity = request.args.get("granularity", "daily")
    if granularity not in ("daily", "weekly", "monthly"):
        granularity = "daily"

    days = request.args.get("days", 30, type=int)
    days = max(1, min(days, 365))

    data = get_trend_data(project_id, granularity, days)
    return jsonify(data)


# ------------------------------------------------------------------
# JSON API: Queue status (live table)
# ------------------------------------------------------------------

@dashboard_bp.route("/api/dashboard/queue")
@login_required
def api_queue():
    """Return current execution queue (running and pending)."""
    data = get_queue_status()
    return jsonify({"queue": data})


# ------------------------------------------------------------------
# JSON API: Recent failures (with Allure links)
# ------------------------------------------------------------------

@dashboard_bp.route("/api/dashboard/failures")
@login_required
def api_failures():
    """Return recent failed tests with Allure report links.

    Query params: project_id (required), limit (default 20).
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    limit = request.args.get("limit", 20, type=int)
    limit = max(1, min(limit, 100))

    data = get_recent_failures(project_id, limit)
    return jsonify({"failures": data})


# ------------------------------------------------------------------
# JSON API: Global overview (all projects)
# ------------------------------------------------------------------

@dashboard_bp.route("/api/dashboard/overview")
@login_required
def api_global_overview():
    """Return aggregate metrics across all projects."""
    overview = get_global_overview()
    projects = get_all_projects_health()
    return jsonify({"overview": overview, "projects": projects})
