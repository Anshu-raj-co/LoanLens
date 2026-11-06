"""Signed session tokens (JWT, HS256, PyJWT)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ALGORITHM = "HS256"
ISSUER = "loanlens"
REQUIRED_CLAIMS = ("sub", "role", "iat", "exp", "iss")


class TokenError(Exception):
    """The token is missing, expired, tampered with or otherwise not valid."""


def issue_token(
    user_id: int, role: str, key: str, minutes: int, now: datetime | None = None
) -> tuple[str, datetime]:
    """A signed token for ``user_id`` with ``role``; returns the token and its expiry."""
    now = now or datetime.now(UTC)
    expires = now + timedelta(minutes=minutes)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": expires, "iss": ISSUER}
    return jwt.encode(payload, key, algorithm=ALGORITHM), expires


def decode_token(token: str, key: str, now: datetime | None = None) -> dict[str, Any]:
    """The verified claims of ``token``; raises :class:`TokenError` if it is not valid.

    ``now`` judges expiry at a given moment (tests); otherwise the current time is used.
    """
    if not token or not isinstance(token, str):
        raise TokenError("no token")
    options: dict[str, Any] = {"require": list(REQUIRED_CLAIMS), "verify_exp": now is None}
    try:
        claims = jwt.decode(token, key, algorithms=[ALGORITHM], issuer=ISSUER, options=options)
    except jwt.PyJWTError:
        raise TokenError("invalid") from None
    if now is not None and not (isinstance(claims["exp"], int | float)
                                and claims["exp"] > now.timestamp()):  # fmt: skip
        raise TokenError("expired")
    if not str(claims.get("sub", "")).isdigit() or not isinstance(claims.get("role"), str):
        raise TokenError("invalid claims")
    return claims
