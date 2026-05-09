"""Token authentication decorator for the REST API."""

import logging
from functools import wraps

from flask import g, jsonify, request

from app.models.api_token import ApiToken

logger = logging.getLogger(__name__)


def token_required(f):
    """Verify ``Authorization: Bearer <token>`` header.

    On success the matched :class:`ApiToken` is stored in ``g.api_token``
    and its owning user id in ``g.api_user_id``.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header."}), 401

        raw_token = auth_header[7:].strip()
        if not raw_token:
            return jsonify({"error": "Empty Bearer token."}), 401

        token = ApiToken.verify_token(raw_token)
        if token is None:
            return jsonify({"error": "Invalid, expired, or revoked token."}), 401

        g.api_token = token
        g.api_user_id = token.user_id
        return f(*args, **kwargs)

    return decorated
