"""Password hashing (argon2id), the password policy and email validation."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 128
MAX_EMAIL_LENGTH = 254
COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")

# argon2-cffi's defaults follow the RFC 9106 low-memory profile (time cost 3, 64 MiB,
# parallelism 4); the type is pinned to argon2id explicitly.
HASHER = PasswordHasher(type=Type.ID)

_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
EMAIL_PROBLEM = "Enter a valid email address, for example name@example.com."


def normalise_email(email: str) -> str:
    """Trim and lower-case an email address; raise ``ValueError`` if it is not valid."""
    value = (email or "").strip().lower()
    local = value.partition("@")[0]
    if (
        not value
        or len(value) > MAX_EMAIL_LENGTH
        or len(local) > 64
        or ".." in value
        or local.startswith(".")
        or local.endswith(".")
        or not _EMAIL.fullmatch(value)
    ):
        raise ValueError(EMAIL_PROBLEM)
    return value


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    """The built-in list of common passwords (lower-case)."""
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(s.strip().lower() for s in lines if s.strip() and not s.startswith("#"))


def password_problems(password: str, email: str | None = None) -> list[str]:
    """Plain-English reasons why ``password`` is not allowed (empty list if it is fine)."""
    password = password or ""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use at most {MAX_LENGTH} characters.")
    if password.strip().lower() in common_passwords():
        problems.append("This password is too common. Choose one that is harder to guess.")
    if email and password.strip().lower() == email.strip().lower():
        problems.append("The password must not be the same as the email address.")
    return problems


def hash_password(password: str) -> str:
    """argon2id hash of ``password`` (includes a random salt and the parameters)."""
    return HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True if ``password`` matches the stored hash. Never raises for a bad password."""
    try:
        return HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with older parameters and should be refreshed."""
    try:
        return HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


_dummy: dict[int, str] = {}


def dummy_verify(password: str) -> None:
    """Spend the same time as a real check, so unknown emails are not revealed by timing."""
    key = id(HASHER)
    if key not in _dummy:
        _dummy[key] = HASHER.hash("loanlens timing equaliser")
    verify_password(_dummy[key], password or "")
