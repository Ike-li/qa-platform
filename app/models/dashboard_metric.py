"""DashboardMetric model for pre-aggregated daily test statistics."""

from datetime import datetime, timezone

from app.extensions import db


class DashboardMetric(db.Model):
    """Pre-aggregated daily metrics per project for fast dashboard rendering.

    One row per (project, date) combination, computed nightly by Celery Beat.
    """

    __tablename__ = "dashboard_metrics"

    __table_args__ = (
        db.UniqueConstraint("project_id", "date", name="uq_dashboard_metric_project_date"),
    )

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = db.Column(db.Date, nullable=False, index=True)

    # Counts
    total_runs = db.Column(db.Integer, nullable=False, default=0)
    pass_count = db.Column(db.Integer, nullable=False, default=0)
    fail_count = db.Column(db.Integer, nullable=False, default=0)
    skip_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)

    # Derived
    pass_rate = db.Column(db.Float, nullable=False, default=0.0)
    avg_duration = db.Column(db.Float, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = db.relationship(
        "Project",
        backref=db.backref("dashboard_metrics", lazy="dynamic"),
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardMetric project_id={self.project_id} date={self.date} "
            f"pass_rate={self.pass_rate}>"
        )
