"""REST API blueprint at /api/v1."""

from flask import Blueprint

api_bp = Blueprint(
    "api",
    __name__,
    url_prefix="/api/v1",
)

from app.api import auth  # noqa: E402, F401
from app.api import executions  # noqa: E402, F401
from app.api import projects  # noqa: E402, F401
