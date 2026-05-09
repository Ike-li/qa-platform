"""ApiToken model for programmatic API access.

Tokens follow the format ``qap_{random_32_chars}`` and are stored
as SHA-256 hashes.  The raw token is shown once at creation time.
"""

import hashlib
import secrets
from datetime import datetime, timezone

from app.extensions import db

_TOKEN_PREFIX = "qap_"
_TOKEN_BODY_LEN = 32


class ApiToken(db.Model):
    """An API token belonging to a user."""

    __tablename__ = "api_tokens"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = db.Column(db.String(120), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)

    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = db.relationship(
        "User",
        backref=db.backref("api_tokens", lazy="dynamic", cascade="all, delete-orphan"),
    )

    # ------------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_raw_token() -> str:
        """Generate a new raw token string (``qap_`` + 32 random hex chars)."""
        return f"{_TOKEN_PREFIX}{secrets.token_hex(_TOKEN_BODY_LEN // 2)}"

    @staticmethod
    def hash_token(raw: str) -> str:
        """Return the SHA-256 hex digest of *raw*."""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create_token(cls, user_id: int, name: str, expires_at=None) -> tuple:
        """Create and persist a new token.

        Returns ``(model_instance, raw_token)`` -- the raw token is only
        available at this point and cannot be recovered later.
        """
        raw = cls.generate_raw_token()
        token = cls(
            user_id=user_id,
            name=name,
            token_hash=cls.hash_token(raw),
            expires_at=expires_at,
        )
        db.session.add(token)
        db.session.commit()
        return token, raw

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    @classmethod
    def verify_token(cls, raw: str) -> "ApiToken | None":
        """Look up an active, non-expired, non-revoked token by its raw value.

        Returns the :class:`ApiToken` instance or ``None``.
        """
        token_hash = cls.hash_token(raw)
        token = cls.query.filter_by(token_hash=token_hash).first()
        if token is None:
            return None
        if token.revoked_at is not None:
            return None
        if token.expires_at and token.expires_at < datetime.now(timezone.utc):
            return None
        # Update last_used_at
        token.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        return token

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now(timezone.utc)

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired

    @property
    def display_token(self) -> str:
        """Show only the first 8 chars + ellipsis for UI display."""
        return f"{_TOKEN_PREFIX}{'*' * 28}"

    def revoke(self) -> None:
        """Mark this token as revoked."""
        self.revoked_at = datetime.now(timezone.utc)
        db.session.commit()

    def __repr__(self) -> str:
        return f"<ApiToken id={self.id} user={self.user_id} name={self.name!r}>"
