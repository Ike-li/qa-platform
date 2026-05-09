"""User model with role-based access control."""

import enum
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class Role(enum.Enum):
    """Application roles ordered by privilege level (highest first)."""

    SUPER_ADMIN = "super_admin"
    PROJECT_LEAD = "project_lead"
    TESTER = "tester"
    VISITOR = "visitor"


# Permission matrix: role -> set of permissions
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.SUPER_ADMIN: {
        "user.manage",
        "project.create",
        "project.edit",
        "project.delete",
        "execution.trigger",
        "execution.view",
        "report.view",
        "config.manage",
        "audit.view",
    },
    Role.PROJECT_LEAD: {
        "project.create",
        "project.edit",
        "execution.trigger",
        "execution.view",
        "report.view",
    },
    Role.TESTER: {
        "execution.trigger",
        "execution.view",
        "report.view",
    },
    Role.VISITOR: {
        "execution.view",
        "report.view",
    },
}


class User(UserMixin, db.Model):
    """Application user with role-based permissions."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(
        db.Enum(Role),
        nullable=False,
        default=Role.TESTER,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ------------------------------------------------------------------
    # Flask-Login required properties (already provided by UserMixin, but
    # explicit here for clarity)
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:  # type: ignore[override]
        return True

    @property
    def is_anonymous(self) -> bool:  # type: ignore[override]
        return False

    def get_id(self) -> str:
        return str(self.id)

    # ------------------------------------------------------------------
    # RBAC helpers
    # ------------------------------------------------------------------

    def has_permission(self, permission: str) -> bool:
        """Return True if the user's role grants *permission*."""
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def has_project_permission(self, permission: str, project_id: int) -> bool:
        """Check if user has a permission within a specific project.

        Falls back to global role permissions for SUPER_ADMIN.
        Project owner always has full access.
        """
        if self.role == Role.SUPER_ADMIN:
            return True

        from app.models.project_membership import ProjectMembership, PROJECT_ROLE_PERMISSIONS
        membership = ProjectMembership.query.filter_by(
            user_id=self.id, project_id=project_id,
        ).first()

        if membership is None:
            from app.models.project import Project
            project = db.session.get(Project, project_id)
            if project and project.owner_id == self.id:
                return True
            return False

        return permission in PROJECT_ROLE_PERMISSIONS.get(membership.role, set())

    def has_role(self, *roles) -> bool:
        """Return True if the user's role is in *roles*.

        Accepts both Role enum values and string values (e.g., 'super_admin').
        """
        for r in roles:
            if isinstance(r, str):
                if self.role.value == r:
                    return True
            elif isinstance(r, Role):
                if self.role == r:
                    return True
        return False

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def role_display(self) -> str:
        return self.role.value.replace("_", " ").title()

    def __repr__(self) -> str:
        return f"<User {self.username!r} role={self.role.value}>"
