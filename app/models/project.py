"""Project model with Fernet-encrypted git credentials."""

from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.extensions import db


class Project(db.Model):
    """A QA project linked to a remote git repository."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True, default="")
    git_url = db.Column(db.String(512), nullable=False)
    git_branch = db.Column(db.String(120), nullable=False, default="main")
    git_credential = db.Column(db.Text, nullable=True)  # Fernet-encrypted token
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    owner = db.relationship("User", backref=db.backref("projects", lazy="dynamic"))
    suites = db.relationship(
        "TestSuite",
        backref="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------------
    # Credential helpers (Fernet encryption)
    # ------------------------------------------------------------------

    def set_credential(self, plaintext: str | None) -> None:
        """Encrypt and store *plaintext* as the git credential.

        Pass ``None`` or empty string to clear the credential.
        """
        if not plaintext:
            self.git_credential = None
            return
        key = current_app.config["FERNET_KEY"]
        f = Fernet(key.encode() if isinstance(key, str) else key)
        self.git_credential = f.encrypt(plaintext.encode()).decode()

    def get_credential(self) -> str | None:
        """Decrypt and return the stored git credential, or ``None``."""
        if not self.git_credential:
            return None
        key = current_app.config["FERNET_KEY"]
        try:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.decrypt(self.git_credential.encode()).decode()
        except (InvalidToken, ValueError):
            return None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def suite_count(self) -> int:
        return self.suites.count()

    @property
    def test_case_count(self) -> int:
        from app.models.test_case import TestCase
        from app.models.test_suite import TestSuite

        return (
            db.session.query(db.func.count(TestCase.id))
            .join(TestSuite, TestSuite.id == TestCase.suite_id)
            .filter(TestSuite.project_id == self.id)
            .scalar()
        )

    @property
    def repo_path(self) -> str:
        """Local filesystem path for the cloned repository."""
        return f"/data/repos/{self.id}"

    def __repr__(self) -> str:
        return f"<Project {self.name!r} id={self.id}>"
