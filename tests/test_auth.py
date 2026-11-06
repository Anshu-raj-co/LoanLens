"""Authentication service: hashing, password policy, lockout, tokens, roles, bootstrap, CLI."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app_support import TEST_PASSWORD, new_email, new_session
from argon2 import PasswordHasher, Type
from sqlalchemy import select

from loanlens import auth, storage
from loanlens.auth import cli, passwords, settings, tokens
from loanlens.auth import service as svc
from loanlens.db.engine import DatabaseError, session_scope
from loanlens.db.models import AuthEvent, User

OTHER_PASSWORD = "Other-" + uuid.uuid4().hex[:12]


def _url() -> str:
    return storage.resolve_url()


def _user(email: str) -> User:
    with session_scope(_url()) as session:
        return session.execute(select(User).where(User.email == email)).scalar_one()


def _events() -> list[AuthEvent]:
    with session_scope(_url()) as session:
        return list(session.execute(select(AuthEvent).order_by(AuthEvent.id)).scalars())


def _manager() -> auth.SignedIn:
    return new_session(auth.MANAGER)


# ---- Hashing ---------------------------------------------------------------------------------


def test_production_hasher_is_argon2id_with_library_defaults() -> None:
    import importlib

    fresh = importlib.reload(passwords)  # the module as shipped, not the fast test hasher
    try:
        assert fresh.HASHER.type is Type.ID
        default = PasswordHasher()
        assert fresh.HASHER.time_cost == default.time_cost >= 2
        assert fresh.HASHER.memory_cost == default.memory_cost >= 19 * 1024
        assert fresh.hash_password("a long passphrase").startswith("$argon2id$")
    finally:
        importlib.reload(passwords)


def test_hash_and_verify() -> None:
    first, second = (
        passwords.hash_password("correct horse"),
        passwords.hash_password("correct horse"),
    )
    assert first.startswith("$argon2id$") and first != second  # random salt
    assert "correct horse" not in first
    assert passwords.verify_password(first, "correct horse")
    assert not passwords.verify_password(first, "Correct horse")
    assert not passwords.verify_password("not-a-hash", "x")
    assert not passwords.needs_rehash(first)
    stronger = PasswordHasher(time_cost=2, memory_cost=2048, parallelism=1, type=Type.ID)
    assert stronger.check_needs_rehash(first)
    assert passwords.needs_rehash("not-a-hash")


# ---- Password policy and email ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short-pw1", "at least 10"),
        ("x" * 129, "at most 128"),
        ("password123", "too common"),
        ("QWERTYUIOP", "too common"),
        ("loanlens-demo", "too common"),
        ("Me@Example.com", "same as the email"),
        ("", "at least 10"),
    ],
)
def test_password_policy_rejects(password: str, problem: str) -> None:
    problems = passwords.password_problems(password, "me@example.com")
    assert any(problem in p for p in problems), problems


@pytest.mark.parametrize("password", ["a" * 9 + "b", "x" * 128, "plum river lamp 42"])
def test_password_policy_accepts(password: str) -> None:
    assert passwords.password_problems(password, "me@example.com") == []


def test_common_password_list_is_loaded() -> None:
    common = passwords.common_passwords()
    assert len(common) > 100 and "password123" in common
    assert all(p == p.lower() for p in common)


@pytest.mark.parametrize("email", [" Me@Example.COM ", "a.b+tag@sub.example.co.in"])
def test_valid_emails_are_lower_cased(email: str) -> None:
    assert passwords.normalise_email(email) == email.strip().lower()


@pytest.mark.parametrize(
    "email",
    ["", "plain", "a@b", "a@@b.com", "a b@c.com", "a..b@c.com", ".a@b.com", "a@-b.com",
     "x" * 65 + "@b.com", "a@" + "b" * 250 + ".com", "a@b.c_m"],
)  # fmt: skip
def test_invalid_emails(email: str) -> None:
    with pytest.raises(ValueError, match="valid email"):
        passwords.normalise_email(email)


# ---- Registration ----------------------------------------------------------------------------


def test_register_applicant() -> None:
    signed_in = auth.register_applicant("New.Person@Example.COM", TEST_PASSWORD)
    principal = signed_in.principal
    assert principal.email == "new.person@example.com" and principal.role == auth.APPLICANT
    assert not principal.must_change_password and not principal.is_manager
    user = _user("new.person@example.com")
    assert user.password_hash.startswith("$argon2id$")
    assert str(uuid.UUID(user.audit_ref)) == user.audit_ref and user.audit_ref != str(user.id)
    assert user.is_active and user.failed_attempts == 0 and user.created_at is not None
    assert auth.principal_from_token(signed_in.token) == principal
    with pytest.raises(auth.AccountError, match="already exists"):
        auth.register_applicant("NEW.person@example.com", TEST_PASSWORD)


@pytest.mark.parametrize(
    ("email", "password", "problem"),
    [
        ("bad-email", TEST_PASSWORD, "valid email"),
        ("ok@example.com", "short", "at least 10"),
        ("ok@example.com", "ok@example.com", "same as the email"),
        ("ok@example.com", None, "fill in the password"),
    ],
)
def test_register_rejects_bad_input(email, password, problem) -> None:
    with pytest.raises(auth.InputError) as exc:
        auth.register_applicant(email, password)
    assert any(problem in p for p in exc.value.problems)
    assert password is None or password not in str(exc.value) or password == email


def test_audit_refs_are_unique() -> None:
    refs = {new_session().principal.audit_ref for _ in range(3)}
    assert len(refs) == 3


# ---- Sign-in and lockout ---------------------------------------------------------------------


def test_sign_in_success_updates_last_login() -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    assert _user(email).last_login_at is None
    signed_in = auth.sign_in(email.upper(), TEST_PASSWORD)
    assert signed_in.principal.email == email
    assert _user(email).last_login_at is not None
    assert signed_in.expires_at > datetime.now(UTC) + timedelta(minutes=59)


@pytest.mark.parametrize("case", ["unknown", "wrong", "invalid_email", "empty", "not_a_string"])
def test_every_sign_in_failure_has_the_same_message(case: str) -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    attempt = {
        "unknown": ("nobody@example.com", TEST_PASSWORD),
        "wrong": (email, "wrong-password-1"),
        "invalid_email": ("not an email", TEST_PASSWORD),
        "empty": ("", ""),
        "not_a_string": (None, None),
    }[case]
    with pytest.raises(auth.LoginFailed) as exc:
        auth.sign_in(*attempt)
    assert str(exc.value) == "Incorrect email or password"


def test_inactive_user_cannot_sign_in() -> None:
    manager = _manager()
    target = new_session()
    auth.set_active(manager.principal, target.principal.user_id, False)
    with pytest.raises(auth.LoginFailed, match="Incorrect email or password"):
        auth.sign_in(target.principal.email, TEST_PASSWORD)
    assert _events()[-1].reason == "inactive"


def test_lockout_after_five_failures_and_unlock_after_fifteen_minutes() -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    start = datetime.now(UTC)
    for i in range(4):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(email, "wrong-password-1", now=start)
        assert _user(email).failed_attempts == i + 1
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(email, "wrong-password-1", now=start)
    locked_until = _user(email).locked_until.replace(tzinfo=UTC)
    assert locked_until == pytest.approx(start + timedelta(minutes=15), abs=timedelta(seconds=1))
    with pytest.raises(auth.LoginFailed, match="Incorrect email or password"):  # same message
        auth.sign_in(email, TEST_PASSWORD, now=start + timedelta(minutes=14))
    assert [e.reason for e in _events()][-2:] == ["wrong_password_locked", "locked"]
    signed_in = auth.sign_in(email, TEST_PASSWORD, now=start + timedelta(minutes=15, seconds=1))
    assert signed_in.principal.email == email
    user = _user(email)
    assert user.failed_attempts == 0 and user.locked_until is None


def test_success_resets_the_failure_count() -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    for _ in range(4):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(email, "wrong-password-1")
    auth.sign_in(email, TEST_PASSWORD)
    assert _user(email).failed_attempts == 0
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(email, "wrong-password-1")
    assert _user(email).locked_until is None  # counting started again


def test_lockout_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv(settings.ENV_LOCKOUT_ATTEMPTS, "2")
    monkeypatch.setenv(settings.ENV_LOCKOUT_MINUTES, "1")
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    start = datetime.now(UTC)
    for _ in range(2):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(email, "wrong-password-1", now=start)
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(email, TEST_PASSWORD, now=start + timedelta(seconds=30))
    auth.sign_in(email, TEST_PASSWORD, now=start + timedelta(seconds=61))


def test_old_hash_is_upgraded_on_sign_in(monkeypatch) -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    old = _user(email).password_hash
    stronger = PasswordHasher(time_cost=2, memory_cost=2048, parallelism=1, type=Type.ID)
    monkeypatch.setattr(passwords, "HASHER", stronger)
    auth.sign_in(email, TEST_PASSWORD)
    new = _user(email).password_hash
    assert new != old and "m=2048" in new


# ---- Tokens and sessions ---------------------------------------------------------------------


def test_token_contents_and_expiry() -> None:
    signed_in = new_session()
    key = settings.signing_key().value
    claims = jwt.decode(signed_in.token, key, algorithms=["HS256"], issuer="loanlens")
    assert claims["sub"] == str(signed_in.principal.user_id) and claims["role"] == "applicant"
    assert claims["exp"] - claims["iat"] == 60 * 60
    assert signed_in.principal.email not in signed_in.token  # no email in the token
    later = datetime.now(UTC) + timedelta(minutes=61)
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(signed_in.token, now=later)
    assert auth.principal_from_token(signed_in.token, now=later - timedelta(minutes=2))


def test_session_length_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv(settings.ENV_SESSION_MINUTES, "5")
    signed_in = new_session()
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(signed_in.token, now=datetime.now(UTC) + timedelta(minutes=6))


def test_expired_token_is_rejected_in_real_time() -> None:
    key = settings.signing_key().value
    past = datetime.now(UTC) - timedelta(hours=2)
    user = new_session().principal
    token, _ = tokens.issue_token(user.user_id, user.role, key, 60, now=past)
    with pytest.raises(auth.InvalidSession, match="session has ended"):
        auth.principal_from_token(token)


def test_tampered_tokens_are_rejected() -> None:
    signed_in = new_session()
    key = settings.signing_key().value
    header, payload, signature = signed_in.token.split(".")
    forged = jwt.encode(
        {"sub": str(signed_in.principal.user_id), "role": "manager", "iat": 1,
         "exp": 4_000_000_000, "iss": "loanlens"}, "a-different-key-that-is-long-enough!!",
        algorithm="HS256",
    )  # fmt: skip
    unsigned = jwt.encode(
        {"sub": "1", "role": "manager", "iat": 1, "exp": 4_000_000_000, "iss": "loanlens"},
        None, algorithm="none",
    )  # fmt: skip
    no_role = jwt.encode(
        {"sub": "1", "iat": 1, "exp": 4_000_000_000, "iss": "loanlens"}, key, algorithm="HS256"
    )
    bad_sub = jwt.encode(
        {"sub": "abc", "role": "x", "iat": 1, "exp": 4_000_000_000, "iss": "loanlens"}, key,
        algorithm="HS256",
    )  # fmt: skip
    for token in (
        f"{header}.{payload}.{signature[:-2]}xx", f"{header}.{payload[:-2]}AA.{signature}",
        forged, unsigned, no_role, bad_sub, "", None, "not.a.token",
    ):  # fmt: skip
        with pytest.raises(auth.InvalidSession):
            auth.principal_from_token(token)


def test_role_in_token_must_match_the_account() -> None:
    applicant = new_session().principal
    key = settings.signing_key().value
    token, _ = tokens.issue_token(applicant.user_id, auth.MANAGER, key, 60)
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(token)


def test_deactivated_or_deleted_account_ends_the_session() -> None:
    manager = _manager()
    target = new_session()
    auth.set_active(manager.principal, target.principal.user_id, False)
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(target.token)
    auth.set_active(manager.principal, target.principal.user_id, True)
    with pytest.raises(auth.InvalidSession):  # reactivation does not revive old sessions
        auth.principal_from_token(target.token)
    fresh = auth.sign_in(target.principal.email, TEST_PASSWORD)
    assert auth.principal_from_token(fresh.token)
    auth.delete_own_account(fresh.principal, TEST_PASSWORD)
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(fresh.token)


def test_sign_out_is_recorded() -> None:
    signed_in = new_session()
    auth.sign_out(signed_in.principal)
    auth.sign_out(None)  # nothing to record
    assert _events()[-1].event_type == "sign_out"


# ---- Settings and the signing key ------------------------------------------------------------


def test_missing_secret_in_development_uses_a_temporary_key(monkeypatch, caplog) -> None:
    monkeypatch.delenv(settings.ENV_SECRET)
    with caplog.at_level(logging.WARNING):
        first = settings.signing_key()
        second = settings.signing_key()
    assert first.ephemeral and first.value == second.value and len(first.value) >= 32
    assert settings.ENV_SECRET in caplog.text and first.value not in caplog.text
    assert caplog.text.count("temporary signing key") == 1  # warned once
    assert first.value not in repr(first)
    signed_in = new_session()  # sessions still work in development
    assert auth.principal_from_token(signed_in.token)


@pytest.mark.parametrize(
    "env", [{settings.ENV_MODE: "production"}, {settings.ENV_MODE: "Production"},
            {settings.ENV_HOSTED: "1"}, {settings.ENV_HOSTED: "true"}],
)  # fmt: skip
def test_missing_secret_in_production_refuses_to_start(monkeypatch, env) -> None:
    monkeypatch.delenv(settings.ENV_SECRET)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(settings.ConfigurationError, match="will not start"):
        settings.signing_key()
    with pytest.raises(settings.ConfigurationError):
        auth.sign_in("a@example.com", "whatever-123")


def test_production_with_a_secret_works(monkeypatch) -> None:
    monkeypatch.setenv(settings.ENV_HOSTED, "1")
    assert not settings.signing_key().ephemeral
    assert not settings.is_production({settings.ENV_HOSTED: "0"})


def test_short_secret_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(settings.ENV_SECRET, "too-short")
    with pytest.raises(settings.ConfigurationError, match="too short"):
        settings.signing_key()


def test_invalid_numeric_settings(monkeypatch) -> None:
    assert settings.load_settings() == settings.AuthSettings()
    monkeypatch.setenv(settings.ENV_LOCKOUT_ATTEMPTS, "zero")
    monkeypatch.setenv(settings.ENV_SESSION_MINUTES, "0")
    with pytest.raises(settings.ConfigurationError) as exc:
        settings.load_settings()
    assert settings.ENV_LOCKOUT_ATTEMPTS in str(exc.value)
    assert settings.ENV_SESSION_MINUTES in str(exc.value)


# ---- Roles in the service layer --------------------------------------------------------------


def test_applicant_cannot_use_manager_functions() -> None:
    applicant = new_session().principal
    other = new_session().principal
    calls = [
        lambda: auth.list_users(applicant),
        lambda: auth.create_manager(applicant, new_email(), OTHER_PASSWORD),
        lambda: auth.set_active(applicant, other.user_id, False),
        lambda: auth.set_temporary_password(applicant, other.user_id, OTHER_PASSWORD),
    ]
    for call in calls:
        with pytest.raises(auth.PermissionDenied, match="bank managers only"):
            call()
    assert auth.sign_in(other.email, TEST_PASSWORD)  # nothing changed


def test_no_principal_means_no_access() -> None:
    for call in (
        lambda: auth.list_users(None),
        lambda: auth.change_password(None, "a", "b"),
        lambda: auth.delete_own_account(None, "a"),
        lambda: auth.require_role("not a principal"),
    ):
        with pytest.raises(auth.InvalidSession):
            call()


def test_forged_principal_is_checked_against_the_database() -> None:
    applicant = new_session().principal
    forged = svc.Principal(applicant.user_id, applicant.email, auth.MANAGER, applicant.audit_ref)
    with pytest.raises(auth.AuthorisationError, match="could not be verified"):
        auth.list_users(forged)
    copied = svc.Principal(
        applicant.user_id, applicant.email, applicant.role, applicant.audit_ref
    )  # same fields, but not from a sign-in
    with pytest.raises(auth.InvalidSession, match="could not be verified"):
        auth.change_password(copied, TEST_PASSWORD, OTHER_PASSWORD)
    ghost = svc.Principal(9999, "ghost@example.com", auth.MANAGER, str(uuid.uuid4()))
    with pytest.raises(auth.InvalidSession):
        auth.list_users(ghost)


def test_deactivated_manager_loses_access() -> None:
    first, second = _manager(), _manager()
    auth.set_active(first.principal, second.principal.user_id, False)
    with pytest.raises(auth.InvalidSession):
        auth.list_users(second.principal)


# ---- Manager actions -------------------------------------------------------------------------


def test_manager_lists_and_creates_managers() -> None:
    manager = _manager()
    applicant = new_session()
    email = new_email(auth.MANAGER)
    view = auth.create_manager(manager.principal, email.upper(), OTHER_PASSWORD)
    assert view.email == email and view.role == auth.MANAGER and view.must_change_password
    assert view.status == "Active (must change password)"
    users = auth.list_users(manager.principal)
    assert [u.email for u in users][:3] == [email, applicant.principal.email,
                                            manager.principal.email]  # fmt: skip
    assert not hasattr(users[0], "password_hash")
    signed_in = auth.sign_in(email, OTHER_PASSWORD)
    assert signed_in.principal.must_change_password and signed_in.principal.is_manager
    with pytest.raises(auth.InputError):
        auth.create_manager(manager.principal, new_email(), "short")
    with pytest.raises(auth.AccountError):
        auth.create_manager(manager.principal, email, OTHER_PASSWORD)


def test_deactivate_and_reactivate() -> None:
    manager = _manager()
    target = new_session()
    view = auth.set_active(manager.principal, target.principal.user_id, False)
    assert view.status == "Deactivated" and not view.is_active
    view = auth.set_active(manager.principal, target.principal.user_id, True)
    assert view.status == "Active"
    assert auth.sign_in(target.principal.email, TEST_PASSWORD)
    kinds = [(e.event_type, e.actor_id) for e in _events()]
    assert ("user_deactivated", manager.principal.user_id) in kinds
    assert ("user_reactivated", manager.principal.user_id) in kinds


def test_manager_cannot_act_on_own_account_or_remove_last_manager() -> None:
    manager = _manager()
    with pytest.raises(auth.AccountError, match="your own account"):
        auth.set_active(manager.principal, manager.principal.user_id, False)
    with pytest.raises(auth.AccountError, match="your own account"):
        auth.set_temporary_password(manager.principal, manager.principal.user_id, OTHER_PASSWORD)
    with pytest.raises(auth.AccountError, match="no longer exists"):
        auth.set_active(manager.principal, 9999, False)
    with pytest.raises(auth.AccountError, match="only active manager"):
        auth.delete_own_account(manager.principal, TEST_PASSWORD)


def test_temporary_password_resets_and_unlocks() -> None:
    manager = _manager()
    target = new_session()
    email = target.principal.email
    for _ in range(5):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(email, "wrong-password-1")
    assert _user(email).locked_until is not None
    with pytest.raises(auth.InputError):
        auth.set_temporary_password(manager.principal, target.principal.user_id, email)
    view = auth.set_temporary_password(manager.principal, target.principal.user_id,
                                       OTHER_PASSWORD)  # fmt: skip
    assert view.must_change_password and not view.is_locked
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(email, TEST_PASSWORD)  # the old password no longer works
    signed_in = auth.sign_in(email, OTHER_PASSWORD)
    assert signed_in.principal.must_change_password
    assert ("password_reset", manager.principal.user_id) in [
        (e.event_type, e.actor_id) for e in _events()
    ]


def test_user_view_status_locked() -> None:
    manager = _manager()
    target = new_session()
    for _ in range(5):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(target.principal.email, "wrong-password-1")
    row = next(u for u in auth.list_users(manager.principal) if u.user_id ==
               target.principal.user_id)  # fmt: skip
    assert row.status == "Locked" and row.is_locked


# ---- Own account -----------------------------------------------------------------------------


def test_change_password() -> None:
    signed_in = new_session()
    with pytest.raises(auth.AccountError, match="current password is not correct"):
        auth.change_password(signed_in.principal, "wrong-password-1", OTHER_PASSWORD)
    with pytest.raises(auth.InputError, match="different"):
        auth.change_password(signed_in.principal, TEST_PASSWORD, TEST_PASSWORD)
    with pytest.raises(auth.InputError, match="too common"):
        auth.change_password(signed_in.principal, TEST_PASSWORD, "password123")
    updated = auth.change_password(signed_in.principal, TEST_PASSWORD, OTHER_PASSWORD)
    assert not updated.principal.must_change_password
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(signed_in.principal.email, TEST_PASSWORD)
    assert auth.sign_in(signed_in.principal.email, OTHER_PASSWORD)
    reasons = [(e.event_type, e.success, e.reason) for e in _events()]
    assert ("password_change", False, "wrong_current_password") in reasons
    assert ("password_change", True, None) in reasons


def test_forced_password_change_is_cleared() -> None:
    manager = _manager()
    target = new_session()
    auth.set_temporary_password(manager.principal, target.principal.user_id, OTHER_PASSWORD)
    with pytest.raises(auth.InvalidSession):  # the temporary password ends open sessions
        auth.principal_from_token(target.token)
    temporary = auth.sign_in(target.principal.email, OTHER_PASSWORD)
    assert temporary.principal.must_change_password
    updated = auth.change_password(temporary.principal, OTHER_PASSWORD, "brand new passphrase 9")
    assert not updated.principal.must_change_password
    assert not auth.principal_from_token(updated.token).must_change_password


def test_delete_own_account_unlinks_events() -> None:
    signed_in = new_session()
    user_id, email = signed_in.principal.user_id, signed_in.principal.email
    auth.sign_in(email, TEST_PASSWORD)
    with pytest.raises(auth.AccountError, match="not correct"):
        auth.delete_own_account(signed_in.principal, "wrong-password-1")
    assert _user(email)  # still there
    auth.delete_own_account(signed_in.principal, TEST_PASSWORD)
    with session_scope(_url()) as session:
        assert session.get(User, user_id) is None
    events = _events()
    assert all(e.user_id != user_id and e.actor_id != user_id for e in events)
    assert events[-1].event_type == "account_deleted" and events[-1].user_id is None
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(email, TEST_PASSWORD)
    assert auth.register_applicant(email, TEST_PASSWORD)  # the email can be used again


def test_manager_can_delete_own_account_when_another_manager_exists() -> None:
    first, second = _manager(), _manager()
    auth.delete_own_account(first.principal, TEST_PASSWORD)
    assert auth.manager_count() == 1
    assert [u.email for u in auth.list_users(second.principal)] == [second.principal.email]


# ---- Bootstrap -------------------------------------------------------------------------------


def _bootstrap_env(email: str = "first.manager@example.com", password: str = OTHER_PASSWORD):
    return {settings.ENV_BOOTSTRAP_EMAIL: email, settings.ENV_BOOTSTRAP_PASSWORD: password}


def test_bootstrap_creates_the_first_manager_once(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert auth.bootstrap_from_env(_bootstrap_env())
    assert "Remove LOANLENS_BOOTSTRAP_MANAGER_EMAIL" in caplog.text
    assert OTHER_PASSWORD not in caplog.text and "first.manager" not in caplog.text
    signed_in = auth.sign_in("first.manager@example.com", OTHER_PASSWORD)
    assert signed_in.principal.is_manager and signed_in.principal.must_change_password
    assert not auth.bootstrap_from_env(_bootstrap_env())  # checked once per process
    svc.reset_bootstrap_check()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert not auth.bootstrap_from_env(_bootstrap_env("second@example.com"))
    assert "already exists" in caplog.text and auth.manager_count() == 1


def test_bootstrap_needs_both_values_and_a_valid_password(caplog) -> None:
    assert not auth.bootstrap_from_env({})
    with caplog.at_level(logging.WARNING):
        assert not auth.bootstrap_from_env({settings.ENV_BOOTSTRAP_EMAIL: "a@example.com"})
    assert "Only one of" in caplog.text
    svc.reset_bootstrap_check()
    with caplog.at_level(logging.WARNING):
        assert not auth.bootstrap_from_env(_bootstrap_env(password="password123"))
    assert "too common" in caplog.text and "password123" not in caplog.text
    assert auth.manager_count() == 0


def test_bootstrap_reads_the_environment(monkeypatch) -> None:
    for name, value in _bootstrap_env().items():
        monkeypatch.setenv(name, value)
    assert auth.bootstrap_from_env()
    assert auth.manager_count() == 1


# ---- Command line ----------------------------------------------------------------------------


def _answers(*values: str):
    it = iter(values)
    return lambda prompt: next(it)


def test_cli_creates_manager(capsys) -> None:
    code = cli.main(["create-manager", "--email", "Cli.Manager@Example.com"],
                    getpass=_answers(OTHER_PASSWORD, OTHER_PASSWORD))  # fmt: skip
    out = capsys.readouterr()
    assert code == 0 and "Manager account created" in out.out
    assert OTHER_PASSWORD not in out.out + out.err
    signed_in = auth.sign_in("cli.manager@example.com", OTHER_PASSWORD)
    assert signed_in.principal.is_manager and not signed_in.principal.must_change_password
    assert _events()[0].event_type == "manager_created_cli"


@pytest.mark.parametrize(
    ("answers", "message"),
    [((OTHER_PASSWORD, OTHER_PASSWORD + "x"), "do not match"),
     (("password123", "password123"), "too common")],
)  # fmt: skip
def test_cli_rejects_bad_passwords(capsys, answers, message) -> None:
    code = cli.main(["create-manager", "--email", "m@example.com"], getpass=_answers(*answers))
    err = capsys.readouterr().err
    assert code == 1 and message in err and answers[0] not in err
    assert auth.manager_count() == 0


def test_cli_rejects_duplicates_and_password_arguments(capsys) -> None:
    new_session(auth.MANAGER, email="dup@example.com")
    code = cli.main(["create-manager", "--email", "dup@example.com"],
                    getpass=_answers(OTHER_PASSWORD, OTHER_PASSWORD))  # fmt: skip
    assert code == 1 and "already exists" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:  # there is no way to pass a password as an argument
        cli.main(["create-manager", "--email", "x@example.com", "--password", "secret-123456"])
    assert exc.value.code == 2


def test_cli_reports_database_problems(capsys, monkeypatch) -> None:
    def broken(*_a, **_k):
        raise DatabaseError(svc.DATABASE_MESSAGE)

    monkeypatch.setattr(svc, "create_manager_account", broken)
    code = cli.main(["create-manager", "--email", "m@example.com"],
                    getpass=_answers(OTHER_PASSWORD, OTHER_PASSWORD))  # fmt: skip
    assert code == 1 and "could not be reached" in capsys.readouterr().err


def test_module_entry_point(monkeypatch) -> None:
    import runpy

    monkeypatch.setattr("sys.argv", ["loanlens.auth", "create-manager", "--email", "e@x.com"])
    monkeypatch.setattr("getpass.getpass", _answers(OTHER_PASSWORD, OTHER_PASSWORD))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("loanlens.auth", run_name="__main__")
    assert exc.value.code == 0


# ---- Database errors -------------------------------------------------------------------------


def test_unreachable_database_gives_an_accounts_message(monkeypatch) -> None:
    url = "postgresql://someone:hunter2-not-real@127.0.0.1:1/none"
    with pytest.raises(DatabaseError) as exc:
        auth.sign_in("a@example.com", "whatever-123", url=url)
    assert "accounts database" in str(exc.value) and "hunter2" not in str(exc.value)


# ---- No secrets at rest or in logs -----------------------------------------------------------


def test_no_plaintext_password_or_token_in_database_events_or_logs(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    applicant_password = "Applicant-" + uuid.uuid4().hex
    manager_password = "Manager-" + uuid.uuid4().hex
    temporary = "Temporary-" + uuid.uuid4().hex
    changed = "Changed-" + uuid.uuid4().hex
    manager = new_session(auth.MANAGER, password=manager_password)
    applicant = auth.register_applicant(new_email(), applicant_password)
    tokens_seen = [manager.token, applicant.token]
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(applicant.principal.email, "Wrong-" + applicant_password)
    tokens_seen.append(auth.sign_in(applicant.principal.email, applicant_password).token)
    auth.set_temporary_password(manager.principal, applicant.principal.user_id, temporary)
    temp_session = auth.sign_in(applicant.principal.email, temporary)
    fresh = auth.change_password(temp_session.principal, temporary, changed)
    tokens_seen += [temp_session.token, fresh.token]
    auth.bootstrap_from_env(_bootstrap_env("boot@example.com", "Boot-" + manager_password))
    secrets_used = [applicant_password, manager_password, temporary, changed,
                    "Boot-" + manager_password, *tokens_seen]  # fmt: skip

    db_file = storage.db_path()
    raw = db_file.read_bytes()
    with sqlite3.connect(db_file) as conn:
        dump = "\n".join(conn.iterdump())
        event_rows = conn.execute("SELECT * FROM auth_events").fetchall()
        columns = [r[1] for r in conn.execute("PRAGMA table_info(auth_events)")]
    assert columns == ["id", "occurred_at", "user_id", "actor_id", "event_type", "success",
                       "reason"]  # fmt: skip
    events_text = repr(event_rows)
    for secret in secrets_used:
        assert secret.encode() not in raw
        assert secret not in dump and secret not in events_text and secret not in caplog.text
    assert applicant.principal.email not in events_text  # no email in events either
    assert "$argon2id$" in dump  # only hashes are stored


# ---- Session invalidation (token version) ----------------------------------------------------


def test_stolen_old_token_is_rejected_after_password_change() -> None:
    email = new_email()
    auth.register_applicant(email, TEST_PASSWORD)
    stolen = auth.sign_in(email, TEST_PASSWORD)  # e.g. a token copied from another device
    current = auth.sign_in(email, TEST_PASSWORD)
    fresh = auth.change_password(current.principal, TEST_PASSWORD, OTHER_PASSWORD)
    for old in (stolen.token, current.token):
        with pytest.raises(auth.InvalidSession):
            auth.principal_from_token(old)
    assert auth.principal_from_token(fresh.token).email == email  # this session continues
    assert fresh.principal.token_version == current.principal.token_version + 1
    with pytest.raises(auth.InvalidSession):  # the stale principal is refused as well
        auth.verify_principal(current.principal)
    assert auth.verify_principal(fresh.principal) == fresh.principal


@pytest.mark.parametrize("action", ["temporary_password", "deactivate", "reactivate"])
def test_manager_actions_end_the_users_sessions(action) -> None:
    manager = _manager()
    target = new_session()
    tid = target.principal.user_id
    if action == "temporary_password":
        auth.set_temporary_password(manager.principal, tid, OTHER_PASSWORD)
    elif action == "deactivate":
        auth.set_active(manager.principal, tid, False)
    else:
        auth.set_active(manager.principal, tid, False)
        middle = target.token
        auth.set_active(manager.principal, tid, True)
        with pytest.raises(auth.InvalidSession):
            auth.principal_from_token(middle)
    with pytest.raises(auth.InvalidSession):
        auth.principal_from_token(target.token)
    assert auth.principal_from_token(manager.token)  # the manager's own session is unaffected


def test_token_version_claim_is_required() -> None:
    import jwt as pyjwt

    user = new_session().principal
    key = settings.signing_key().value
    claims = {"sub": str(user.user_id), "role": user.role, "iat": 1, "exp": 4_000_000_000,
              "iss": "loanlens"}  # fmt: skip
    for extra in ({}, {"ver": "0"}, {"ver": True}, {"ver": 5}):
        token = pyjwt.encode({**claims, **extra}, key, algorithm="HS256")
        with pytest.raises(auth.InvalidSession):
            auth.principal_from_token(token)
    good = pyjwt.encode({**claims, "ver": 0}, key, algorithm="HS256")
    assert auth.principal_from_token(good).user_id == user.user_id
