"""API endpoints for querying projects."""

from flask import jsonify

from app.api import api_bp
from app.api.auth import token_required
from app.models.project import Project


@api_bp.route("/projects", methods=["GET"])
@token_required
def list_projects():
    """Return all projects."""
    projects = Project.query.order_by(Project.name).all()
    return jsonify({
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "git_url": p.git_url,
                "git_branch": p.git_branch,
                "repo_path": p.repo_path,
            }
            for p in projects
        ]
    })


@api_bp.route("/projects/<int:project_id>", methods=["GET"])
@token_required
def get_project(project_id: int):
    """Return detailed info for a single project including suites."""
    project = Project.query.get(project_id)
    if project is None:
        return jsonify({"error": "Project not found."}), 404

    suites = []
    if hasattr(project, "suites"):
        suites = [
            {"id": s.id, "name": s.name, "path_in_repo": s.path_in_repo}
            for s in project.suites.all()
        ]

    schedules = []
    if hasattr(project, "cron_schedules"):
        schedules = [
            {"id": cs.id, "cron_expr": cs.cron_expr, "is_active": cs.is_active}
            for cs in project.cron_schedules.all()
        ]

    return jsonify({
        "id": project.id,
        "name": project.name,
        "git_url": project.git_url,
        "git_branch": project.git_branch,
        "repo_path": project.repo_path,
        "suites": suites,
        "cron_schedules": schedules,
    })
