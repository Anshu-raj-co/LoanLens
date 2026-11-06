"""Accounts, sign-in, sessions and role checks: the service layer every UI calls.

Roles are enforced here, not only in the pages: every function that acts on behalf of a
user takes the signed-in :class:`Principal` and checks its role first.

Nothing in this module logs or stores a password, a token or an email address in an event.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from loanlens import storage
from loanlens.auth import passwords, settings, tokens
from loanlens.db.engine import DatabaseError, session_scope
from loanlens.db.models import AuthEvent, User

logger = logging.getLogger(__name__)

APPLICANT = "applicant"
MANAGER = "manager"
ROLES = (APPLICANT, MANAGER)
ROLE_LABELS = {APPLICANT: "Applicant", MANAGER: "Bank manager"}

GENERIC_LOGIN_ERROR = "Incorrect email or password"
SESSION_ENDED = "Your session has ended. Please sign in again."
DATABASE_MESSAGE = (
    "The accounts database could not be reached, so signing in and account changes are not "
    "available right now. Ask the administrator to check the DATABASE_URL setting."
)


# ---- Errors (every message is safe to show to the user) ------------------------------------


class AuthError(Exception):
    """Base class; ``str(exc)`` is a plain message for the user."""


class LoginFailed(AuthError):
    """Any sign-in failure. The message never says which part was wrong."""

    def __init__(self) -> None:
        super().__init__(GENERIC_LOGIN_ERROR)


class InvalidSession(AuthError):
    """No session, or the session token is expired, tampered with or no longer valid."""

    def __init__(self, message: str = SESSION_ENDED) -> None:
        super().__init__(message)


class PermissionDenied(AuthError):
    """The signed-in user's role does not allow this action."""


class InputError(AuthError):
    """Invalid input; ``problems`` lists each issue in plain English."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(" ".join(problems))


class AccountError(AuthError):
    """The action is not possible for this account (for example the email is taken)."""


# ---- Validated inputs ------------------------------------------------------------------------


def _email(value: str) -> str:
    return passwords.normalise_email(value)


Email = Annotated[str, AfterValidator(_email)]


class _Input(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True, extra="forbid")


class NewAccount(_Input):
    """Email plus a new password that must pass the password policy."""

    email: Email
    password: str = Field(max_length=10_000)
    role: str = APPLICANT

    def model_post_init(self, _context: object) -> None:
        problems = passwords.password_problems(self.password, self.email)
        if self.role not in ROLES:
            problems.append("Unknown role.")
        if problems:
            raise InputError(problems)


class NewPassword(_Input):
    """A new password checked against the policy (and the account's email)."""

    password: str = Field(max_length=10_000)
    email: str | None = None

    def model_post_init(self, _context: object) -> None:
        problems = passwords.password_problems(self.password, self.email)
        if problems:
            raise InputError(problems)


def _validate(model: type[_Input], **data: object) -> _Input:
    """Build ``model``; turn any validation error into :class:`InputError` (no input echoed)."""
    try:
        return model(**data)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            msg = str(err.get("msg", ""))
            msg = msg.removeprefix("Value error, ")
            if err.get("type") in {"string_type", "missing"}:
                msg = f"Please fill in the {err['loc'][0]} field."
            problems.append(msg)
        raise InputError(problems) from None


# ---- Results ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The signed-in user, as the pages and services see it."""

    user_id: int
    email: str
    role: str
    audit_ref: str
    must_change_password: bool = False

    @property
    def is_manager(self) -> bool:
        return self.role == MANAGER

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


@dataclass(frozen=True)
class SignedIn:
    """A successful sign-in: the session token (never logged) and the principal."""

    token: str = field(repr=False)
    principal: Principal
    expires_at: datetime


@dataclass(frozen=True)
class UserView:
    """One row of the manager's user list (no password hash)."""

    user_id: int
    email: str
    role: str
    is_active: bool
    is_locked: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None

    @property
    def status(self) -> str:
        if not self.is_active:
            return "Deactivated"
        if self.is_locked:
            return "Locked"
        if self.must_change_password:
            return "Active (must change password)"
        return "Active"


# ---- Helpers ---------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; every stored time is UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _url(url: str | None) -> str:
    return url or storage.resolve_url()


@contextmanager
def _db(url: str | None) -> Iterator[DbSession]:
    """A database session whose failures carry an accounts-specific friendly message."""
    try:
        with session_scope(_url(url)) as session:
            yield session
    except DatabaseError as exc:
        if str(exc) == DATABASE_MESSAGE:
            raise
        raise DatabaseError(DATABASE_MESSAGE) from None


def _event(
    session: DbSession,
    event_type: str,
    success: bool,
    user_id: int | None = None,
    actor_id: int | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        AuthEvent(
            occurred_at=_now(), user_id=user_id, actor_id=actor_id, event_type=event_type,
            success=success, reason=reason,
        )
    )  # fmt: skip


def _principal(user: User) -> Principal:
    return Principal(
        user_id=user.id, email=user.email, role=user.role, audit_ref=user.audit_ref,
        must_change_password=bool(user.must_change_password),
    )  # fmt: skip


def _view(user: User, now: datetime) -> UserView:
    locked = _aware(user.locked_until)
    return UserView(
        user_id=user.id, email=user.email, role=user.role, is_active=bool(user.is_active),
        is_locked=bool(locked and locked > now),
        must_change_password=bool(user.must_change_password),
        created_at=_aware(user.created_at), last_login_at=_aware(user.last_login_at),
    )  # fmt: skip


def _active_managers(session: DbSession) -> int:
    query = (
        select(func.count()).select_from(User).where(User.role == MANAGER, User.is_active.is_(True))
    )
    return int(session.execute(query).scalar_one())


def _by_email(session: DbSession, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _issue(user: User) -> SignedIn:
    key = settings.signing_key()
    token, expires = tokens.issue_token(
        user.id, user.role, key.value, settings.load_settings().session_minutes
    )
    return SignedIn(token=token, principal=_principal(user), expires_at=expires)


# ---- Role checks -----------------------------------------------------------------------------


def require_role(principal: Principal | None, *roles: str) -> Principal:
    """Return ``principal`` if it is signed in and (when ``roles`` are given) has one of them."""
    if principal is None or not isinstance(principal, Principal):
        raise InvalidSession("Please sign in to continue.")
    if roles and principal.role not in roles:
        allowed = " or ".join(ROLE_LABELS[r].lower() + "s" for r in roles)
        raise PermissionDenied(f"This is available to {allowed} only.")
    return principal


def require_manager(principal: Principal | None) -> Principal:
    """Shortcut for :func:`require_role` with the manager role."""
    return require_role(principal, MANAGER)


def _load_actor(session: DbSession, principal: Principal, *roles: str) -> User:
    """Re-read the acting account: it must still exist, be active and hold the role."""
    user = session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise InvalidSession()
    if roles and user.role not in roles:
        raise PermissionDenied("This is available to bank managers only.")
    return user


# ---- Accounts --------------------------------------------------------------------------------


def _create_user(
    session: DbSession,
    data: NewAccount,
    must_change_password: bool,
    event_type: str,
    actor_id: int | None = None,
) -> User:
    if _by_email(session, data.email) is not None:
        raise AccountError(
            "An account with this email already exists. Sign in instead, or use another email."
        )
    user = User(
        audit_ref=str(uuid.uuid4()), email=data.email,
        password_hash=passwords.hash_password(data.password), role=data.role, is_active=True,
        must_change_password=must_change_password, created_at=_now(), failed_attempts=0,
    )  # fmt: skip
    session.add(user)
    session.flush()
    _event(session, event_type, True, user_id=user.id, actor_id=actor_id)
    return user


def register_applicant(email: str, password: str, *, url: str | None = None) -> SignedIn:
    """Create an applicant account (public sign-up) and sign it in."""
    data = _validate(NewAccount, email=email, password=password, role=APPLICANT)
    with _db(url) as session:
        user = _create_user(session, data, False, "sign_up")
        signed_in = _issue(user)
    return signed_in


def create_manager(
    principal: Principal | None, email: str, temporary_password: str, *, url: str | None = None
) -> UserView:
    """A manager creates another manager, who must change the password at first sign-in."""
    actor = require_manager(principal)
    data = _validate(NewAccount, email=email, password=temporary_password, role=MANAGER)
    with _db(url) as session:
        _load_actor(session, actor, MANAGER)
        user = _create_user(session, data, True, "manager_created", actor_id=actor.user_id)
        view = _view(user, _now())
    return view


def create_manager_account(
    email: str, password: str, *, must_change_password: bool = False, url: str | None = None,
    event_type: str = "manager_created_cli",
) -> UserView:  # fmt: skip
    """Create a manager without a signed-in principal (command line and bootstrap only)."""
    data = _validate(NewAccount, email=email, password=password, role=MANAGER)
    with _db(url) as session:
        user = _create_user(session, data, must_change_password, event_type)
        view = _view(user, _now())
    return view


def manager_count(*, url: str | None = None) -> int:
    """Number of active manager accounts."""
    with _db(url) as session:
        return _active_managers(session)


_bootstrap_checked: set[str] = set()


def bootstrap_from_env(environ: Mapping[str, str] | None = None, *, url: str | None = None) -> bool:
    """Create the first manager from the bootstrap variables, once, if no manager exists.

    Returns True if a manager was created. Runs its check once per database per process.
    The variables should be removed afterwards; a warning says so while they are set.
    """
    environ = os.environ if environ is None else environ
    email = environ.get(settings.ENV_BOOTSTRAP_EMAIL, "").strip()
    password = environ.get(settings.ENV_BOOTSTRAP_PASSWORD, "")
    resolved = _url(url)
    if not (email or password) or resolved in _bootstrap_checked:
        return False
    _bootstrap_checked.add(resolved)
    if not (email and password):
        logger.warning(
            "Only one of %s and %s is set; no manager was created.",
            settings.ENV_BOOTSTRAP_EMAIL, settings.ENV_BOOTSTRAP_PASSWORD,
        )  # fmt: skip
        return False
    with _db(resolved) as session:
        has_manager = session.execute(
            select(func.count()).select_from(User).where(User.role == MANAGER)
        ).scalar_one()
    if has_manager:
        logger.warning(
            "A manager already exists, so the bootstrap settings were ignored. Remove %s and "
            "%s from the environment.", settings.ENV_BOOTSTRAP_EMAIL,
            settings.ENV_BOOTSTRAP_PASSWORD,
        )  # fmt: skip
        return False
    try:
        create_manager_account(
            email, password, must_change_password=True, url=resolved, event_type="bootstrap"
        )
    except InputError as exc:
        logger.warning("The bootstrap manager was not created: %s", " ".join(exc.problems))
        return False
    logger.warning(
        "The first manager account was created from the bootstrap settings. Remove %s and %s "
        "from the environment now.", settings.ENV_BOOTSTRAP_EMAIL,
        settings.ENV_BOOTSTRAP_PASSWORD,
    )  # fmt: skip
    return True


def reset_bootstrap_check() -> None:
    """Forget which databases were checked for bootstrap (tests use this)."""
    _bootstrap_checked.clear()


# ---- Sign-in and sessions --------------------------------------------------------------------


def sign_in(
    email: str, password: str, *, url: str | None = None, now: datetime | None = None
) -> SignedIn:
    """Check the credentials and return a session; every failure raises :class:`LoginFailed`.

    After ``lockout_attempts`` wrong passwords in a row the account is locked for
    ``lockout_minutes``; while locked even the right password is refused. Deactivated
    accounts cannot sign in.
    """
    config = settings.load_settings()
    key = settings.signing_key()  # fail early (and clearly) on a configuration problem
    now = now or _now()
    password = password if isinstance(password, str) else ""
    try:
        address = passwords.normalise_email(email if isinstance(email, str) else "")
    except ValueError:
        passwords.dummy_verify(password)
        with _db(url) as session:
            _event(session, "sign_in", False, reason="invalid_email")
        raise LoginFailed() from None
    result: SignedIn | None = None
    with _db(url) as session:
        user = _by_email(session, address)
        if user is None:
            passwords.dummy_verify(password)
            _event(session, "sign_in", False, reason="unknown_account")
        else:
            locked = _aware(user.locked_until)
            if locked and locked > now:
                passwords.dummy_verify(password)
                _event(session, "sign_in", False, user.id, reason="locked")
            else:
                if locked:  # the lock has expired: start counting again
                    user.locked_until, user.failed_attempts = None, 0
                if not passwords.verify_password(user.password_hash, password):
                    user.failed_attempts = (user.failed_attempts or 0) + 1
                    reason = "wrong_password"
                    if user.failed_attempts >= config.lockout_attempts:
                        user.locked_until = now + timedelta(minutes=config.lockout_minutes)
                        user.failed_attempts = 0
                        reason = "wrong_password_locked"
                    _event(session, "sign_in", False, user.id, reason=reason)
                elif not user.is_active:
                    _event(session, "sign_in", False, user.id, reason="inactive")
                else:
                    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
                    if passwords.needs_rehash(user.password_hash):
                        user.password_hash = passwords.hash_password(password)
                    _event(session, "sign_in", True, user.id)
                    token, expires = tokens.issue_token(
                        user.id, user.role, key.value, config.session_minutes, now=now
                    )
                    result = SignedIn(token=token, principal=_principal(user), expires_at=expires)
    if result is None:
        raise LoginFailed()
    return result


def principal_from_token(
    token: str | None, *, url: str | None = None, now: datetime | None = None
) -> Principal:
    """Validate a session token and re-read the account; raises :class:`InvalidSession`.

    The token must have a valid signature and must not have expired, and the account must
    still exist, be active and have the role named in the token.
    """
    key = settings.signing_key()
    try:
        claims = tokens.decode_token(token or "", key.value, now=now)
    except tokens.TokenError:
        raise InvalidSession() from None
    with _db(url) as session:
        user = session.get(User, int(claims["sub"]))
        if user is None or not user.is_active or user.role != claims["role"]:
            raise InvalidSession()
        return _principal(user)


def sign_out(principal: Principal | None, *, url: str | None = None) -> None:
    """Record the sign-out (the token itself is dropped by the caller)."""
    if principal is None:
        return
    with _db(url) as session:
        _event(session, "sign_out", True, principal.user_id)


# ---- Own account -----------------------------------------------------------------------------


def change_password(
    principal: Principal | None, current_password: str, new_password: str,
    *, url: str | None = None,
) -> Principal:  # fmt: skip
    """Change the signed-in user's own password (the current password is required)."""
    me = require_role(principal)
    with _db(url) as session:
        user = _load_actor(session, me)
        if not passwords.verify_password(user.password_hash, current_password or ""):
            _event(session, "password_change", False, user.id, reason="wrong_current_password")
            failed = True
        else:
            failed = False
            if passwords.verify_password(user.password_hash, new_password or ""):
                raise InputError(["Choose a new password that is different from the current one."])
            _validate(NewPassword, password=new_password, email=user.email)
            user.password_hash = passwords.hash_password(new_password)
            user.must_change_password = False
            _event(session, "password_change", True, user.id)
            updated = _principal(user)
    if failed:
        raise AccountError("The current password is not correct.")
    return updated


def delete_own_account(
    principal: Principal | None, password: str, *, url: str | None = None
) -> None:
    """Delete the signed-in user's account after confirming the password.

    The user row is removed, so records that only carry its audit reference can no longer be
    linked to a person. Earlier sign-in events keep no link (their user id is cleared). The
    last active manager cannot delete their own account.
    """
    me = require_role(principal)
    problem: str | None = None
    with _db(url) as session:
        user = _load_actor(session, me)
        if not passwords.verify_password(user.password_hash, password or ""):
            _event(session, "account_deleted", False, user.id, reason="wrong_password")
            problem = "The password is not correct, so the account was not deleted."
        elif user.role == MANAGER and user.is_active and _active_managers(session) <= 1:
            problem = (
                "You are the only active manager, so this account cannot be deleted. Create "
                "another manager first."
            )
        else:
            session.execute(
                update(AuthEvent).where(AuthEvent.user_id == user.id).values(user_id=None)
            )
            session.execute(
                update(AuthEvent).where(AuthEvent.actor_id == user.id).values(actor_id=None)
            )
            session.delete(user)
            _event(session, "account_deleted", True)
    if problem:
        raise AccountError(problem)


# ---- Manager actions -------------------------------------------------------------------------


def list_users(principal: Principal | None, *, url: str | None = None) -> list[UserView]:
    """Every account, newest first (managers only)."""
    actor = require_manager(principal)
    now = _now()
    with _db(url) as session:
        _load_actor(session, actor, MANAGER)
        users = session.execute(select(User).order_by(User.id.desc())).scalars().all()
        return [_view(u, now) for u in users]


def _other_user(session: DbSession, actor: Principal, user_id: int, action: str) -> User:
    if user_id == actor.user_id:
        raise AccountError(f"You cannot {action} your own account here. Use the Account page.")
    user = session.get(User, user_id)
    if user is None:
        raise AccountError("That account no longer exists.")
    return user


def set_active(
    principal: Principal | None, user_id: int, active: bool, *, url: str | None = None
) -> UserView:
    """Deactivate or reactivate another account (managers only).

    Managers cannot change their own status, so at least one active manager always remains.
    """
    actor = require_manager(principal)
    with _db(url) as session:
        _load_actor(session, actor, MANAGER)
        user = _other_user(session, actor, int(user_id), "deactivate or reactivate")
        user.is_active = bool(active)
        if active:
            user.failed_attempts, user.locked_until = 0, None
        event = "user_reactivated" if active else "user_deactivated"
        _event(session, event, True, user.id, actor_id=actor.user_id)
        view = _view(user, _now())
    return view


def set_temporary_password(
    principal: Principal | None, user_id: int, temporary_password: str,
    *, url: str | None = None,
) -> UserView:  # fmt: skip
    """Give another account a temporary password; it must be changed at the next sign-in.

    This also clears a lockout. It is how a forgotten password is reset.
    """
    actor = require_manager(principal)
    with _db(url) as session:
        _load_actor(session, actor, MANAGER)
        user = _other_user(session, actor, int(user_id), "set a temporary password for")
        _validate(NewPassword, password=temporary_password, email=user.email)
        user.password_hash = passwords.hash_password(temporary_password)
        user.must_change_password = True
        user.failed_attempts, user.locked_until = 0, None
        _event(session, "password_reset", True, user.id, actor_id=actor.user_id)
        view = _view(user, _now())
    return view
