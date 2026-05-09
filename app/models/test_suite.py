"""TestSuite model representing a test file within a project."""

import enum
from datetime import datetime, timezone

from app.extensions import db


class TestType(enum.Enum):
    """Classification of test suites."""

    API = "API"
    UI = "UI"
    UNIT = "UNIT"
    PERFORMANCE = "PERFORMANCE"


class TestSuite(db.Model):
    """A collection of test cases derived from a single test file in the repo."""

    __tablename__ = "test_suites"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(200), nullable=False)
    path_in_repo = db.Column(db.String(512), nullable=False)
    test_type = db.Column(
        db.Enum(TestType),
        nullable=False,
        default=TestType.UNIT,
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
    cases = db.relationship(
        "TestCase",
        backref="suite",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def case_count(self) -> int:
        return self.cases.count()

    def __repr__(self) -> str:
        return f"<TestSuite {self.name!r} project_id={self.project_id}>"
