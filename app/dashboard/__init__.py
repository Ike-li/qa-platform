"""Dashboard blueprint for metrics visualization and queue monitoring."""

from flask import Blueprint

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard",
    template_folder="../templates/dashboard",
)

from app.dashboard import routes  # noqa: E402, F401
