"""TestCase model representing an individual test function within a suite."""

from datetime import datetime, timezone

from app.extensions import db


class TestCase(db.Model):
    """An individual test function discovered in a test file."""

    __tablename__ = "test_cases"

    id = db.Column(db.Integer, primary_key=True)
    suite_id = db.Column(
        db.Integer,
        db.ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    test_params = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TestCase {self.name!r} suite_id={self.suite_id}>"
