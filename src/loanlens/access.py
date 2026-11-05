"""Bank manager gate for the prototype (NOT real authentication).

The password is read, in order, from the environment variable ``LOANLENS_MANAGER_PASSWORD``
or the Streamlit secret ``manager_password`` (``.streamlit/secrets.toml``, gitignored). If
neither is set, the documented local-demo default :data:`DEMO_PASSWORD` is used and the page
says so. Real authentication (accounts, roles, audit) is future work.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_VAR = "LOANLENS_MANAGER_PASSWORD"
SECRET_KEY = "manager_password"
# Local demo only; documented in README.md and USER_GUIDE.md. Set ENV_VAR or the secret to
# replace it anywhere the app is shared.
DEMO_PASSWORD = "loanlens-demo"


@dataclass(frozen=True)
class GatePassword:
    """The password the gate checks against and where it came from."""

    value: str
    source: str  # "environment", "secrets" or "demo default"

    @property
    def is_demo_default(self) -> bool:
        return self.source == "demo default"


def resolve_password(
    environ: Mapping[str, str] | None = None, secrets: Mapping[str, object] | None = None
) -> GatePassword:
    """Pick the gate password: environment variable, then Streamlit secret, then demo default."""
    environ = os.environ if environ is None else environ
    env_value = (environ.get(ENV_VAR) or "").strip()
    if env_value:
        return GatePassword(env_value, "environment")
    if secrets is not None:
        try:
            secret_value = str(secrets.get(SECRET_KEY) or "").strip()
        except Exception:  # noqa: BLE001 - a broken secrets file must not crash the page
            secret_value = ""
        if secret_value:
            return GatePassword(secret_value, "secrets")
    return GatePassword(DEMO_PASSWORD, "demo default")


def check_password(entered: str | None, expected: GatePassword) -> bool:
    """Constant-time comparison of the entered password with the expected one."""
    if not entered:
        return False
    return hmac.compare_digest(entered.encode("utf-8"), expected.value.encode("utf-8"))
