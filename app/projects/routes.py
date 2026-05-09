"""Project CRUD routes with RBAC and git integration."""

import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.project import Project
from app.models.test_suite import TestSuite
from app.models.user import Role
from app.projects import projects_bp
from app.projects.forms import ProjectForm
from app.projects.services import discover_suites
from app.utils.audit import log_audit

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# List (any authenticated user with project.create or execution.view)
# ------------------------------------------------------------------

@projects_bp.route("/")
@login_required
def list_projects():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("q", "").strip()

    query = Project.query
    if search:
        query = query.filter(
            db.or_(
                Project.name.ilike(f"%{search}%"),
                Project.description.ilike(f"%{search}%"),
            )
        )

    pagination = query.order_by(Project.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template(
        "projects/list.html",
        pagination=pagination,
        projects=pagination.items,
        search=search,
    )


# ------------------------------------------------------------------
# Detail
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>")
@login_required
def detail_project(id: int):
    project = Project.query.get_or_404(id)
    suites = project.suites.order_by(TestSuite.name).all()
    return render_template(
        "projects/detail.html",
        project=project,
        suites=suites,
    )


# ------------------------------------------------------------------
# Create
# ------------------------------------------------------------------

@projects_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_project():
    if not current_user.has_permission("project.create"):
        abort(403)

    form = ProjectForm()
    if form.validate_on_submit():
        project = Project(
            name=form.name.data.strip(),
            description=form.description.data or "",
            git_url=form.git_url.data.strip(),
            git_branch=form.git_branch.data.strip() or "main",
            owner_id=current_user.id,
        )
        if form.git_credential.data:
            project.set_credential(form.git_credential.data)

        db.session.add(project)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        log_audit(
            "project.create",
            resource_type="project",
            resource_id=project.id,
            new_value={"name": project.name, "git_url": project.git_url},
        )
        flash(f"项目 '{project.name}' 创建成功。", "success")
        return redirect(url_for("projects.detail_project", id=project.id))

    return render_template("projects/form.html", form=form, editing=False)


# ------------------------------------------------------------------
# Edit (owner or super_admin)
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(id: int):
    project = Project.query.get_or_404(id)

    if not (project.owner_id == current_user.id or current_user.has_role(Role.SUPER_ADMIN)):
        abort(403)

    form = ProjectForm(obj=project)
    if form.validate_on_submit():
        old_values = {
            "name": project.name,
            "git_url": project.git_url,
            "git_branch": project.git_branch,
            "description": project.description,
        }

        project.name = form.name.data.strip()
        project.git_url = form.git_url.data.strip()
        project.git_branch = form.git_branch.data.strip() or "main"
        project.description = form.description.data or ""

        if form.git_credential.data:
            project.set_credential(form.git_credential.data)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        new_values = {
            "name": project.name,
            "git_url": project.git_url,
            "git_branch": project.git_branch,
            "description": project.description,
        }
        log_audit(
            "project.edit",
            resource_type="project",
            resource_id=project.id,
            old_value=old_values,
            new_value=new_values,
        )
        flash(f"项目 '{project.name}' 更新成功。", "success")
        return redirect(url_for("projects.detail_project", id=project.id))

    return render_template("projects/form.html", form=form, editing=True, project=project)


# ------------------------------------------------------------------
# Delete (super_admin only)
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete_project(id: int):
    project = Project.query.get_or_404(id)

    if not current_user.has_role(Role.SUPER_ADMIN):
        abort(403)

    old_values = {"name": project.name, "git_url": project.git_url}
    project_name = project.name

    db.session.delete(project)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    log_audit(
        "project.delete",
        resource_type="project",
        resource_id=id,
        old_value=old_values,
    )
    flash(f"项目 '{project_name}' 已删除。", "success")
    return redirect(url_for("projects.list_projects"))


# ------------------------------------------------------------------
# Re-pull repository
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>/pull", methods=["POST"])
@login_required
def pull_project(id: int):
    project = Project.query.get_or_404(id)

    if not (project.owner_id == current_user.id or current_user.has_role(Role.SUPER_ADMIN)):
        abort(403)

    from app.tasks.git_tasks import git_sync_project
    git_sync_project.delay(project.id, action="pull")
    log_audit("project.git.pull", resource_type="project", resource_id=project.id)
    flash("仓库拉取已在后台启动，请稍后刷新页面。", "info")
    return redirect(url_for("projects.detail_project", id=project.id))


# ------------------------------------------------------------------
# Re-discover test suites
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>/discover", methods=["POST"])
@login_required
def discover_project(id: int):
    project = Project.query.get_or_404(id)

    if not (project.owner_id == current_user.id or current_user.has_role(Role.SUPER_ADMIN)):
        abort(403)

    try:
        suites = discover_suites(project)
        total_cases = sum(s.case_count for s in suites)
        log_audit(
            "project.discover_suites",
            resource_type="project",
            resource_id=project.id,
            new_value={"suites_found": len(suites), "cases_found": total_cases},
        )
        flash(
            f"发现 {len(suites)} 个测试套件，共 {total_cases} 个测试用例。",
            "success",
        )
    except RuntimeError as exc:
        logger.error("Suite discovery failed for project %s: %s", project.id, exc)
        flash(f"套件发现失败: {exc}", "danger")

    return redirect(url_for("projects.detail_project", id=project.id))


# ------------------------------------------------------------------
# Clone repository (initial clone)
# ------------------------------------------------------------------

@projects_bp.route("/<int:id>/clone", methods=["POST"])
@login_required
def clone_project(id: int):
    project = Project.query.get_or_404(id)

    if not (project.owner_id == current_user.id or current_user.has_role(Role.SUPER_ADMIN)):
        abort(403)

    from app.tasks.git_tasks import git_sync_project
    git_sync_project.delay(project.id, action="clone")
    log_audit("project.git.clone", resource_type="project", resource_id=project.id)
    flash("仓库克隆已在后台启动，请稍后刷新页面。", "info")
    return redirect(url_for("projects.detail_project", id=project.id))
