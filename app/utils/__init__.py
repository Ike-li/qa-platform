"""Utility functions package.

Exports common utilities for use across the application.

Phase 1: encryption helpers (Fernet)
Phase 3: Allure report generation
Phase 4: notification dispatchers
Phase 7: error classes and registration
"""

from app.utils.errors import (  # noqa: F401
    AppError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    register_error_handlers,
)
