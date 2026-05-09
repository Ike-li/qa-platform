"""AllureReport model for generated Allure HTML reports."""

from datetime import datetime, timezone

from app.extensions import db


class AllureReport(db.Model):
    """Metadata for a generated Allure report tied to an execution."""

    __tablename__ = "allure_reports"

    id = db.Column(db.Integer, primary_key=True)

    execution_id = db.Column(
        db.Integer,
        db.ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    report_path = db.Column(db.String(512), nullable=False)
    report_url = db.Column(db.String(512), nullable=False)

    generated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    file_size_mb = db.Column(db.Float, nullable=True)

    # Relationship
    execution = db.relationship(
        "Execution",
        backref=db.backref("allure_report", uselist=False, lazy="joined"),
    )

    def __repr__(self) -> str:
        return f"<AllureReport execution_id={self.execution_id}>"
