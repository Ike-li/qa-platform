"""Executions blueprint for triggering and viewing test runs."""

from flask import Blueprint

executions_bp = Blueprint(
    "executions",
    __name__,
    url_prefix="/executions",
    template_folder="../templates/executions",
)

from app.executions import routes  # noqa: E402, F401
