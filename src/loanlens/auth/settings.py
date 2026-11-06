"""Authentication settings, read from environment variables.

* ``LOANLENS_JWT_SECRET``: key that signs session tokens (at least 32 characters).
  Missing in local development: a temporary key is generated for this process and a
  warning is shown. Missing when ``LOANLENS_ENV=production`` or ``LOANLENS_HOSTED=1``:
  the app refuses to start.
* ``LOANLENS_SESSION_MINUTES`` (default 60), ``LOANLENS_LOCKOUT_ATTEMPTS`` (default 5) and
  ``LOANLENS_LOCKOUT_MINUTES`` (default 15).
* ``LOANLENS_BOOTSTRAP_MANAGER_EMAIL`` and ``LOANLENS_BOOTSTRAP_MANAGER_PASSWORD``: create
  the first manager once, only while no manager exists. Remove them afterwards.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

ENV_SECRET = "LOANLENS_JWT_SECRET"
ENV_MODE = "LOANLENS_ENV"
ENV_HOSTED = "LOANLENS_HOSTED"
ENV_SESSION_MINUTES = "LOANLENS_SESSION_MINUTES"
ENV_LOCKOUT_ATTEMPTS = "LOANLENS_LOCKOUT_ATTEMPTS"
ENV_LOCKOUT_MINUTES = "LOANLENS_LOCKOUT_MINUTES"
ENV_BOOTSTRAP_EMAIL = "LOANLENS_BOOTSTRAP_MANAGER_EMAIL"
ENV_BOOTSTRAP_PASSWORD = "LOANLENS_BOOTSTRAP_MANAGER_PASSWORD"
MIN_SECRET_LENGTH = 32

EPHEMERAL_WARNING = (
    f"{ENV_SECRET} is not set, so a temporary signing key is used. Everyone is signed out "
    f"when the app restarts. Set {ENV_SECRET} before sharing the app."
)


class ConfigurationError(RuntimeError):
    """A setting is missing or invalid; the message is safe to show and names the setting."""


class AuthSettings(BaseModel):
    """Validated session and lockout settings."""

    model_config = ConfigDict(frozen=True)

    session_minutes: int = Field(60, ge=1, le=1440)
    lockout_attempts: int = Field(5, ge=1, le=100)
    lockout_minutes: int = Field(15, ge=1, le=1440)


_SETTING_ENV = {
    "session_minutes": ENV_SESSION_MINUTES,
    "lockout_attempts": ENV_LOCKOUT_ATTEMPTS,
    "lockout_minutes": ENV_LOCKOUT_MINUTES,
}


def load_settings(environ: Mapping[str, str] | None = None) -> AuthSettings:
    """Settings from the environment; an invalid value raises :class:`ConfigurationError`."""
    environ = os.environ if environ is None else environ
    values = {k: environ[v].strip() for k, v in _SETTING_ENV.items() if environ.get(v, "").strip()}
    try:
        return AuthSettings(**values)
    except ValidationError as exc:
        names = ", ".join(_SETTING_ENV[str(e["loc"][0])] for e in exc.errors())
        raise ConfigurationError(
            f"Invalid setting: {names}. Use a whole number within the documented range."
        ) from None


def is_production(environ: Mapping[str, str] | None = None) -> bool:
    """True when ``LOANLENS_ENV=production`` or ``LOANLENS_HOSTED`` is switched on."""
    environ = os.environ if environ is None else environ
    mode = environ.get(ENV_MODE, "").strip().lower()
    hosted = environ.get(ENV_HOSTED, "").strip().lower()
    return mode == "production" or hosted in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SigningKey:
    """The token signing key and whether it is a temporary one."""

    value: str = field(repr=False)
    ephemeral: bool


_ephemeral_key: str | None = None
_lock = threading.Lock()


def signing_key(environ: Mapping[str, str] | None = None) -> SigningKey:
    """The JWT signing key (see the module docstring for the rules)."""
    global _ephemeral_key
    environ = os.environ if environ is None else environ
    secret = environ.get(ENV_SECRET, "").strip()
    if secret:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"{ENV_SECRET} is too short. Use at least {MIN_SECRET_LENGTH} random characters."
            )
        return SigningKey(secret, ephemeral=False)
    if is_production(environ):
        raise ConfigurationError(
            f"{ENV_SECRET} is not set. LoanLens will not start in production or hosted mode "
            f"without it. Set {ENV_SECRET} to at least {MIN_SECRET_LENGTH} random characters."
        )
    with _lock:
        if _ephemeral_key is None:
            _ephemeral_key = secrets.token_urlsafe(48)
            logger.warning(EPHEMERAL_WARNING)
    return SigningKey(_ephemeral_key, ephemeral=True)


def reset_ephemeral_key() -> None:
    """Forget the temporary key (tests use this)."""
    global _ephemeral_key
    _ephemeral_key = None
