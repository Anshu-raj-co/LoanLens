"""API settings, read from environment variables (names in ``.env.example``).

* ``LOANLENS_API_MAX_BATCH``: most applicants in one ``POST /v1/score/batch`` (default 1000).
* ``LOANLENS_API_CORS_ORIGINS``: comma-separated origins allowed by CORS. Empty (the
  default) means CORS is off.
* ``LOANLENS_API_AUTH_LIMIT_PER_CLIENT``, ``LOANLENS_API_AUTH_LIMIT_PER_ACCOUNT`` and
  ``LOANLENS_API_AUTH_WINDOW_SECONDS``: rate limits for ``/v1/auth/login`` and
  ``/v1/auth/register`` (default 10 per client address and 5 per account in 60 seconds).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from loanlens.auth.settings import ConfigurationError

ENV_MAX_BATCH = "LOANLENS_API_MAX_BATCH"
ENV_CORS_ORIGINS = "LOANLENS_API_CORS_ORIGINS"
ENV_LIMIT_CLIENT = "LOANLENS_API_AUTH_LIMIT_PER_CLIENT"
ENV_LIMIT_ACCOUNT = "LOANLENS_API_AUTH_LIMIT_PER_ACCOUNT"
ENV_WINDOW = "LOANLENS_API_AUTH_WINDOW_SECONDS"

_ENV = {
    "max_batch": ENV_MAX_BATCH,
    "auth_limit_per_client": ENV_LIMIT_CLIENT,
    "auth_limit_per_account": ENV_LIMIT_ACCOUNT,
    "auth_window_seconds": ENV_WINDOW,
}


class ApiSettings(BaseModel):
    """Validated API settings."""

    model_config = ConfigDict(frozen=True)

    max_batch: int = Field(1000, ge=1, le=10_000)
    cors_origins: tuple[str, ...] = ()
    auth_limit_per_client: int = Field(10, ge=1, le=10_000)
    auth_limit_per_account: int = Field(5, ge=1, le=10_000)
    auth_window_seconds: int = Field(60, ge=1, le=86_400)


def load_api_settings(environ: Mapping[str, str] | None = None) -> ApiSettings:
    """Settings from the environment; an invalid value raises :class:`ConfigurationError`."""
    environ = os.environ if environ is None else environ
    values: dict[str, object] = {
        k: environ[v].strip() for k, v in _ENV.items() if environ.get(v, "").strip()
    }
    origins = [o.strip() for o in environ.get(ENV_CORS_ORIGINS, "").split(",") if o.strip()]
    values["cors_origins"] = tuple(origins)
    try:
        return ApiSettings(**values)
    except ValidationError as exc:
        names = ", ".join(_ENV.get(str(e["loc"][0]), ENV_CORS_ORIGINS) for e in exc.errors())
        raise ConfigurationError(
            f"Invalid setting: {names}. Use a whole number within the documented range."
        ) from None
