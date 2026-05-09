"""REST API blueprint at /api/v1."""

import logging
import os
import time
from functools import wraps

from flask import g, jsonify
from flask_smorest import Blueprint
from redis import Redis

api_bp = Blueprint(
    "api",
    __name__,
    url_prefix="/api/v1",
)

# ------------------------------------------------------------------
# Rate limiting via Redis sorted sets (sliding window)
# ------------------------------------------------------------------

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
_redis = Redis.from_url(REDIS_URL)

_RATE_LIMIT_MAX = 10       # max requests
_RATE_LIMIT_WINDOW = 60    # per N seconds


def rate_limit(f):
    """Decorator: enforce per-token sliding-window rate limit.

    Must be placed AFTER ``@token_required`` so ``g.api_token`` is available.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        key = f"api_rate_limit:{g.api_token.id}"
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW
        try:
            pipe = _redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, _RATE_LIMIT_WINDOW)
            results = pipe.execute()
            current_count = results[2]
            if current_count > _RATE_LIMIT_MAX:
                return jsonify({"error": "Rate limit exceeded. Max 10 requests per minute."}), 429
        except Exception:
            logger.warning(
                "Rate-limit check failed for token %d, allowing request",
                g.api_token.id,
            )
        return f(*args, **kwargs)

    return decorated


from app.api import auth  # noqa: E402, F401
from app.api import executions  # noqa: E402, F401
from app.api import projects  # noqa: E402, F401
