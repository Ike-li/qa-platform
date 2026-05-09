"""API endpoints for querying projects."""

from flask import g, jsonify

from app.api import api_bp, rate_limit
from app.api.auth import token_required
from app.extensions import db
from app.models.project import Project
from app.models.project_membership import ProjectMembership
from app.models.user import Role, User


def _user_visible_project_ids(user: User) -> list[int] | None:
    """Return project IDs the user may access, or None for SUPER_ADMIN (all)."""
    if user.role == Role.SUPER_ADMIN:
        return None

    owned_ids = [p.id for p in user.projects.all()]
    member_ids = [
        m.project_id for m in ProjectMembership.query.filter_by(user_id=user.id).all()
    ]
    return list(set(owned_ids) | set(member_ids))


@api_bp.route("/projects", methods=["GET"])
@token_required
@rate_limit
def list_projects():
    """Return projects the authenticated user owns or is a member of.

    SUPER_ADMIN users see all projects.
    """
    user = db.session.get(User, g.api_user_id)
    visible_ids = _user_visible_project_ids(user)
    query = Project.query.order_by(Project.name)
    if visible_ids is not None:
        if not visible_ids:
            return jsonify({"projects": []})
        query = query.filter(Project.id.in_(visible_ids))
    projects = query.all()
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
@rate_limit
def get_project(project_id: int):
    """Return detailed info for a single project including suites."""
    user = db.session.get(User, g.api_user_id)
    visible_ids = _user_visible_project_ids(user)
    if visible_ids is not None and project_id not in visible_ids:
        return jsonify({"error": "项目未找到。"}), 404

    project = db.session.get(Project, project_id)
    if project is None:
        return jsonify({"error": "项目未找到。"}), 404

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
