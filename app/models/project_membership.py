"""Project-level membership and role assignment."""

import enum
from datetime import datetime, timezone

from app.extensions import db


class ProjectRole(enum.Enum):
    """Roles within a specific project."""

    OWNER = "owner"
    LEAD = "lead"
    TESTER = "tester"
    VIEWER = "viewer"


# Project role -> set of project-scoped permissions
PROJECT_ROLE_PERMISSIONS: dict[ProjectRole, set[str]] = {
    ProjectRole.OWNER: {
        "project.settings",
        "project.members.manage",
        "execution.trigger",
        "execution.view",
        "report.view",
    },
    ProjectRole.LEAD: {
        "project.settings",
        "execution.trigger",
        "execution.view",
        "report.view",
    },
    ProjectRole.TESTER: {
        "execution.trigger",
        "execution.view",
        "report.view",
    },
    ProjectRole.VIEWER: {
        "execution.view",
        "report.view",
    },
}


class ProjectMembership(db.Model):
    """Association between a user and a project with a specific role."""

    __tablename__ = "project_memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = db.Column(
        db.Enum(ProjectRole), nullable=False, default=ProjectRole.TESTER,
    )
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False,
    )

    user = db.relationship("User", backref=db.backref("memberships", lazy="dynamic"))
    project = db.relationship("Project", backref=db.backref("memberships", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "project_id", name="uq_user_project"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMembership user={self.user_id} project={self.project_id} role={self.role.value}>"
