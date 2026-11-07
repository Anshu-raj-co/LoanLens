"""Hosted mode (``LOANLENS_HOSTED=1``) and production checks.

A free host such as Streamlit Community Cloud runs only the Streamlit app, with about
1 GB of memory and a disk that is wiped on every restart. With ``LOANLENS_HOSTED=1``:

* settings may come from Streamlit secrets as well as environment variables
  (:func:`apply_secrets`); an environment variable that is already set wins;
* a missing or weak ``LOANLENS_JWT_SECRET`` stops the app (see
  :func:`loanlens.auth.settings.signing_key`), and so does an incomplete or weak pair of
  bootstrap manager settings (:func:`check_settings`);
* batch jobs default to smaller chunks, a lower row cap and a temporary directory
  (:data:`HOSTED_CHUNK_SIZE`, :data:`HOSTED_MAX_ROWS`, :data:`HOSTED_MAX_UPLOAD_MB`,
  :data:`HOSTED_JOBS_DIR`); each can still be set explicitly;
* without an external PostgreSQL ``DATABASE_URL`` a warning says that accounts and audit
  records are lost on restart.

The row cap and chunk size were set from a measured run of the Streamlit app with its
embedded worker on a 200,000-row synthetic file (README, "Deploy").
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

from loanlens.auth.passwords import password_problems
from loanlens.auth.settings import (
    ENV_BOOTSTRAP_EMAIL,
    ENV_BOOTSTRAP_PASSWORD,
    ENV_HOSTED,
    ConfigurationError,
    is_production,
)

ENV_DATABASE_URL = "DATABASE_URL"
HOSTED_CHUNK_SIZE = 5_000
HOSTED_MAX_ROWS = 200_000
HOSTED_MAX_UPLOAD_MB = 50
HOSTED_JOBS_DIR = Path(tempfile.gettempdir()) / "loanlens-jobs"
_TRUE = {"1", "true", "yes", "on"}

EPHEMERAL_DATABASE_WARNING = (
    "Hosted mode without an external PostgreSQL database (DATABASE_URL): accounts, history "
    "and audit records are kept on this host's temporary disk and are lost when it restarts."
)


def is_hosted(environ: Mapping[str, str] | None = None) -> bool:
    """True when ``LOANLENS_HOSTED`` is switched on."""
    environ = os.environ if environ is None else environ
    return environ.get(ENV_HOSTED, "").strip().lower() in _TRUE


def apply_secrets(
    secrets: Mapping[str, Any], environ: MutableMapping[str, str] | None = None
) -> list[str]:
    """Copy LoanLens settings from Streamlit secrets into the environment.

    Only top-level ``DATABASE_URL`` and ``LOANLENS_*`` entries with a plain value are used,
    and only when the environment variable is not already set. Returns the names copied
    (never the values).
    """
    environ = os.environ if environ is None else environ
    applied = []
    for name, value in secrets.items():
        if not (name == ENV_DATABASE_URL or name.startswith("LOANLENS_")):
            continue
        if not isinstance(value, str | int | float | bool) or environ.get(name, "").strip():
            continue
        environ[name] = str(value)
        applied.append(name)
    return sorted(applied)


def check_settings(environ: Mapping[str, str] | None = None) -> list[str]:
    """Check the production or hosted settings that :mod:`loanlens.auth` does not.

    Returns warnings to show. In production or hosted mode an incomplete or weak pair of
    bootstrap manager settings raises :class:`ConfigurationError` (outside those modes it
    is only logged when the bootstrap runs).
    """
    environ = os.environ if environ is None else environ
    warnings: list[str] = []
    if is_production(environ):
        email = environ.get(ENV_BOOTSTRAP_EMAIL, "").strip()
        password = environ.get(ENV_BOOTSTRAP_PASSWORD, "")
        if bool(email) != bool(password):
            raise ConfigurationError(
                f"Only one of {ENV_BOOTSTRAP_EMAIL} and {ENV_BOOTSTRAP_PASSWORD} is set. Set "
                "both to create the first manager, or neither."
            )
        if password and password_problems(password, email):
            raise ConfigurationError(
                f"{ENV_BOOTSTRAP_PASSWORD} is too weak: "
                + " ".join(password_problems(password, email))
            )
    if is_hosted(environ):
        url = environ.get(ENV_DATABASE_URL, "").strip()
        if not url or url.lower().startswith("sqlite"):
            warnings.append(EPHEMERAL_DATABASE_WARNING)
    return warnings
