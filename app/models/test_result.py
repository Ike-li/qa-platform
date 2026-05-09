"""TestResult model for individual test outcomes within an execution."""

import enum
from datetime import datetime, timezone

from app.extensions import db


class TestResultStatus(enum.Enum):
    """Outcome of a single test case."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class TestResult(db.Model):
    """One row per test function executed during a run."""

    __tablename__ = "test_results"

    id = db.Column(db.Integer, primary_key=True)

    execution_id = db.Column(
        db.Integer,
        db.ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id = db.Column(
        db.Integer,
        db.ForeignKey("test_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name = db.Column(db.String(300), nullable=False)
    file_path = db.Column(db.String(512), nullable=True)

    status = db.Column(
        db.Enum(TestResultStatus),
        nullable=False,
        default=TestResultStatus.ERROR,
        index=True,
    )

    duration_sec = db.Column(db.Float, nullable=True)
    error_msg = db.Column(db.Text, nullable=True)
    stacktrace = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    execution = db.relationship(
        "Execution",
        backref=db.backref("results", lazy="dynamic", cascade="all, delete-orphan"),
    )
    case = db.relationship("TestCase", backref=db.backref("results", lazy="dynamic"))

    def __repr__(self) -> str:
        return (
            f"<TestResult {self.name!r} status={self.status.value} "
            f"execution_id={self.execution_id}>"
        )
