"""Admin blueprint for user management."""

from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="../templates/admin",
)

from app.admin import routes  # noqa: E402, F401
