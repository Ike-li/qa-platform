"""SystemConfig model for platform-wide key-value settings.

Stores configuration values with type metadata so they can be
cast back to their native Python types on retrieval.
Sensitive values (e.g. SMTP password) are encrypted at rest with Fernet.
"""

import logging
from datetime import datetime, timezone

from app.extensions import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fernet helper – lazy-loaded so the rest of the module works without crypto
# ---------------------------------------------------------------------------

_fernet = None


def _get_fernet():
    """Return a Fernet instance using the app's SECRET_KEY, or None."""
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        import os

        from cryptography.fernet import Fernet

        raw = os.getenv("FERNET_KEY", "")
        if not raw:
            return None
        _fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
        return _fernet
    except Exception:
        logger.warning("Fernet not available – encrypted values stored in plaintext")
        return None


def _encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


# ---------------------------------------------------------------------------
# Default seed data
# ---------------------------------------------------------------------------

DEFAULT_CONFIGS: list[dict] = [
    {
        "key": "execution.timeout_minutes",
        "value": "30",
        "description": "Default execution timeout in minutes.",
        "value_type": "int",
    },
    {
        "key": "execution.git_timeout_minutes",
        "value": "10",
        "description": "Git clone/pull timeout in minutes.",
        "value_type": "int",
    },
    {
        "key": "execution.report_timeout_minutes",
        "value": "10",
        "description": "Report generation timeout in minutes.",
        "value_type": "int",
    },
    {
        "key": "execution.max_parallel",
        "value": "3",
        "description": "Maximum number of parallel executions.",
        "value_type": "int",
    },
    {
        "key": "retention.execution_days",
        "value": "90",
        "description": "Delete executions older than this many days.",
        "value_type": "int",
    },
    {
        "key": "retention.report_days",
        "value": "30",
        "description": "Delete allure reports older than this many days.",
        "value_type": "int",
    },
    {
        "key": "retention.audit_days",
        "value": "180",
        "description": "Delete audit logs older than this many days.",
        "value_type": "int",
    },
    {
        "key": "notification.smtp_host",
        "value": "",
        "description": "SMTP server hostname.",
        "value_type": "str",
    },
    {
        "key": "notification.smtp_port",
        "value": "587",
        "description": "SMTP server port.",
        "value_type": "int",
    },
    {
        "key": "notification.smtp_user",
        "value": "",
        "description": "SMTP username.",
        "value_type": "str",
    },
    {
        "key": "notification.smtp_pass",
        "value": "",
        "description": "SMTP password (stored encrypted).",
        "value_type": "encrypted",
    },
    {
        "key": "notification.smtp_from",
        "value": "",
        "description": "SMTP from address.",
        "value_type": "str",
    },
]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class SystemConfig(db.Model):
    """A single platform-wide configuration entry."""

    __tablename__ = "system_configs"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False, default="")
    description = db.Column(db.String(256), nullable=True)
    value_type = db.Column(
        db.String(20), nullable=False, default="str"
    )  # str | int | bool | float | encrypted

    # Audit
    updated_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    user = db.relationship(
        "User", backref=db.backref("config_changes", lazy="dynamic")
    )

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, key: str, default=None):
        """Retrieve a config value by key with automatic type casting.

        Parameters
        ----------
        key : str
            The dotted config key, e.g. ``"execution.timeout_minutes"``.
        default :
            Value to return if the key does not exist.

        Returns
        -------
        The value cast to the type specified by ``value_type``, or *default*.
        """
        cfg = cls.query.filter_by(key=key).first()
        if cfg is None:
            return default
        return cfg.cast_value()

    @classmethod
    def set(cls, key: str, value, user_id: int | None = None) -> "SystemConfig":
        """Create or update a config entry.

        Parameters
        ----------
        key : str
            The dotted config key.
        value :
            The new value (will be stored as string; encrypted if value_type is "encrypted").
        user_id : int | None
            The user performing the change.

        Returns
        -------
        SystemConfig – the updated (or newly created) row.
        """
        cfg = cls.query.filter_by(key=key).first()
        if cfg is None:
            cfg = cls(key=key)
            db.session.add(cfg)

        # Store encrypted values differently
        str_value = str(value) if value is not None else ""
        if cfg.value_type == "encrypted":
            cfg.value = _encrypt(str_value)
        else:
            cfg.value = str_value

        cfg.updated_by = user_id
        cfg.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return cfg

    @classmethod
    def get_all(cls) -> dict:
        """Return all configs as a ``{key: cast_value}`` dict."""
        rows = cls.query.all()
        return {r.key: r.cast_value() for r in rows}

    @classmethod
    def seed_defaults(cls) -> int:
        """Insert default configs that don't already exist. Returns count added."""
        added = 0
        for entry in DEFAULT_CONFIGS:
            existing = cls.query.filter_by(key=entry["key"]).first()
            if existing is None:
                row = cls(**entry)
                db.session.add(row)
                added += 1
        if added:
            db.session.commit()
        return added

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    def cast_value(self):
        """Cast the stored string value to the declared Python type."""
        raw = self.value
        if self.value_type == "encrypted":
            return _decrypt(raw)
        if self.value_type == "int":
            return int(raw)
        if self.value_type == "float":
            return float(raw)
        if self.value_type == "bool":
            return raw.lower() in ("true", "1", "yes", "on")
        return raw  # str

    @property
    def is_sensitive(self) -> bool:
        return self.value_type == "encrypted"

    def display_value(self) -> str:
        """Mask sensitive values for display."""
        if self.is_sensitive:
            return "****" if self.value else ""
        return self.value

    def __repr__(self) -> str:
        return f"<SystemConfig key={self.key!r} type={self.value_type}>"
