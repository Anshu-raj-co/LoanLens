"""Streamlit flows: register, sign in, wrong password, access rules, account and users pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app_support import TEST_PASSWORD, new_email, new_session, open_page

from loanlens import auth
from loanlens.auth import settings, tokens

SIGN_IN = "pages/0_Sign_In.py"
CHECK = "pages/1_Check_My_Eligibility.py"
BULK = "pages/2_Bulk_Check.py"
ANALYTICS = "pages/3_Analytics.py"
USERS = "pages/5_Users.py"
ACCOUNT = "pages/6_Account.py"
MANAGER_PAGES = [BULK, ANALYTICS, USERS]
NEW_PASSWORD = "Fresh-passphrase-" + TEST_PASSWORD[-6:]


def _click(at, label: str):
    return next(b for b in at.button if b.label == label).click().run()


def _texts(at) -> str:
    parts = [e.value for kind in ("info", "warning", "error", "success") for e in at.get(kind)]
    return "\n".join(str(p) for p in parts)


def _signed_in(at) -> bool:
    return bool(at.session_state["auth_token"]) if "auth_token" in at.session_state else False


# ---- Sign in page ----------------------------------------------------------------------------


def test_sign_in_page_has_two_tabs(app_path) -> None:
    at = open_page(SIGN_IN).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Sign in", "Create account"]
    assert any("Not signed in" in c.value for c in at.sidebar.caption)
    assert "Bank manager accounts are created by an administrator" in " ".join(
        m.value for m in at.markdown
    )


def test_register_flow(app_path) -> None:
    at = open_page(SIGN_IN).run()
    email = new_email()
    at.text_input(key="signup_email").input(email.upper())
    at.text_input(key="signup_password").input(TEST_PASSWORD)
    at.text_input(key="signup_repeat").input(TEST_PASSWORD)
    _click(at, "Create account")
    assert not at.exception and _signed_in(at)
    from ui_common import escape_md

    shown = escape_md(email)  # user text is shown literally, with Markdown escaped
    assert any(shown in s.value and "Applicant" in s.value for s in at.success)
    assert any(shown in m.value for m in at.sidebar.markdown)
    assert any("Role: Applicant" in c.value for c in at.sidebar.caption)


@pytest.mark.parametrize(
    ("email", "password", "repeat", "message"),
    [
        ("ok@example.com", TEST_PASSWORD, TEST_PASSWORD + "x", "do not match"),
        ("ok@example.com", "password123", "password123", "too common"),
        ("ok@example.com", "short", "short", "at least 10"),
        ("not-an-email", TEST_PASSWORD, TEST_PASSWORD, "valid email"),
    ],
)
def test_register_validation_messages(app_path, email, password, repeat, message) -> None:
    at = open_page(SIGN_IN).run()
    at.text_input(key="signup_email").input(email)
    at.text_input(key="signup_password").input(password)
    at.text_input(key="signup_repeat").input(repeat)
    _click(at, "Create account")
    assert not at.exception and not _signed_in(at)
    assert any(message in e.value for e in at.error), [e.value for e in at.error]


def test_register_existing_email(app_path) -> None:
    existing = new_session().principal.email
    at = open_page(SIGN_IN).run()
    at.text_input(key="signup_email").input(existing)
    at.text_input(key="signup_password").input(TEST_PASSWORD)
    at.text_input(key="signup_repeat").input(TEST_PASSWORD)
    _click(at, "Create account")
    assert any("already exists" in e.value for e in at.error)


def test_sign_in_and_wrong_password(app_path) -> None:
    email = new_session().principal.email
    at = open_page(SIGN_IN).run()
    at.text_input(key="signin_email").input(email)
    at.text_input(key="signin_password").input("not-the-password")
    _click(at, "Sign in")
    assert not at.exception and not _signed_in(at)
    assert [e.value for e in at.error] == ["Incorrect email or password"]
    at.text_input(key="signin_email").input("nobody@example.com")
    at.text_input(key="signin_password").input(TEST_PASSWORD)
    _click(at, "Sign in")
    assert [e.value for e in at.error] == ["Incorrect email or password"]  # same message
    at.text_input(key="signin_email").input(email)
    at.text_input(key="signin_password").input(TEST_PASSWORD)
    _click(at, "Sign in")
    assert not at.exception and _signed_in(at)
    assert any("You are signed in as" in s.value for s in at.success)


def test_lockout_message_is_generic(app_path) -> None:
    email = new_session().principal.email
    for _ in range(5):
        with pytest.raises(auth.LoginFailed):
            auth.sign_in(email, "not-the-password")
    at = open_page(SIGN_IN).run()
    at.text_input(key="signin_email").input(email)
    at.text_input(key="signin_password").input(TEST_PASSWORD)
    _click(at, "Sign in")
    assert [e.value for e in at.error] == ["Incorrect email or password"]
    assert any("locked for 15 minutes" in c.value for c in at.caption)


def test_sign_out(app_path) -> None:
    at = open_page(CHECK).run()
    assert not at.exception and _signed_in(at)
    at.sidebar.button(key="sign_out").click().run()
    assert not at.exception and not _signed_in(at)
    assert any("Please sign in" in i.value for i in at.info)
    assert any("You have signed out" in w.value for w in at.warning)
    assert not at.number_input  # the form is gone


def test_sign_out_from_sign_in_page(app_path) -> None:
    at = open_page(SIGN_IN, role=auth.APPLICANT).run()
    _click(at, "Sign out")
    assert not _signed_in(at)
    assert [t.label for t in at.tabs] == ["Sign in", "Create account"]


# ---- Access rules ----------------------------------------------------------------------------


@pytest.mark.parametrize("page", [CHECK, *MANAGER_PAGES, ACCOUNT])
def test_signed_out_users_are_asked_to_sign_in(app_path, page) -> None:
    at = open_page(page, role=None).run()
    assert not at.exception
    assert any("Please sign in to use this page" in i.value for i in at.info)
    assert not at.number_input and not at.dataframe


@pytest.mark.parametrize("page", ["Home.py", "pages/4_About.py", SIGN_IN])
def test_public_pages_need_no_session(app_path, artifact, page) -> None:
    at = open_page(page, role=None).run()
    assert not at.exception
    assert not any("Please sign in to use this page" in i.value for i in at.info)


@pytest.mark.parametrize("page", MANAGER_PAGES)
def test_applicant_blocked_from_manager_pages(app_path, artifact, page) -> None:
    at = open_page(page, role=auth.APPLICANT).run()
    assert not at.exception
    assert any("bank managers only" in i.value and "Applicant" in i.value for i in at.info)
    assert not at.dataframe and not at.get("plotly_chart") and not at.get("download_button")


@pytest.mark.parametrize("page", [*MANAGER_PAGES, CHECK, ACCOUNT])
def test_manager_allowed(app_path, artifact, page) -> None:
    at = open_page(page, role=auth.MANAGER).run()
    assert not at.exception
    assert not any("bank managers only" in i.value for i in at.info)
    assert not any("Please sign in" in i.value for i in at.info)
    assert any("Role: Bank manager" in c.value for c in at.sidebar.caption)


def test_applicant_can_check_eligibility(app_path, artifact) -> None:
    at = open_page(CHECK, role=auth.APPLICANT).run()
    assert not at.exception and at.number_input
    at.button[0].click().run()
    assert not at.exception
    assert any("Loan type: Personal loan" in c.value for c in at.caption)


def test_expired_session_returns_to_sign_in(app_path) -> None:
    user = new_session().principal
    key = settings.signing_key().value
    old, _ = tokens.issue_token(user.user_id, user.role, key, 60,
                                now=datetime.now(UTC) - timedelta(hours=2))  # fmt: skip
    at = open_page(CHECK, role=None)
    at.session_state["auth_token"] = old
    at.run()
    assert not at.exception and not _signed_in(at)
    assert any("session has ended" in w.value for w in at.warning)
    assert any("Please sign in" in i.value for i in at.info)


def test_tampered_session_returns_to_sign_in(app_path) -> None:
    signed_in = new_session()
    at = open_page(CHECK, role=None)
    at.session_state["auth_token"] = signed_in.token[:-3] + "abc"
    at.run()
    assert any("session has ended" in w.value for w in at.warning)


def test_session_revalidated_on_every_load(app_path) -> None:
    manager = new_session(auth.MANAGER)
    target = new_session()
    at = open_page(CHECK, session=target).run()
    assert at.number_input
    auth.set_active(manager.principal, target.principal.user_id, False)
    at.run()  # the next page load notices the deactivation
    assert not at.number_input and not _signed_in(at)
    assert any("session has ended" in w.value for w in at.warning)


def test_production_without_secret_refuses_to_start(app_path, monkeypatch) -> None:
    monkeypatch.delenv(settings.ENV_SECRET)
    monkeypatch.setenv(settings.ENV_HOSTED, "1")
    at = open_page("Home.py", role=None).run()
    assert not at.exception
    assert any("LoanLens cannot start" in e.value and settings.ENV_SECRET in e.value
               for e in at.error)  # fmt: skip
    assert not at.get("page_link")


def test_development_without_secret_shows_warning(app_path, monkeypatch) -> None:
    monkeypatch.delenv(settings.ENV_SECRET)
    at = open_page("Home.py", role=None).run()
    assert not at.exception
    assert any("temporary signing key" in w.value for w in at.sidebar.warning)


def test_bootstrap_runs_from_the_app(app_path, monkeypatch) -> None:
    monkeypatch.setenv(settings.ENV_BOOTSTRAP_EMAIL, "boot@example.com")
    monkeypatch.setenv(settings.ENV_BOOTSTRAP_PASSWORD, NEW_PASSWORD)
    open_page("Home.py", role=None).run()
    assert auth.manager_count() == 1


# ---- Forced password change and the Account page ---------------------------------------------


def test_forced_password_change(app_path, artifact) -> None:
    session = new_session(auth.MANAGER, must_change_password=True)
    at = open_page(CHECK, session=session).run()
    assert any("must choose a new password" in w.value for w in at.warning)
    assert not at.number_input
    account = open_page(ACCOUNT, session=session).run()
    assert any("must choose a new password" in w.value for w in account.warning)
    account.text_input(key="current_password").input(TEST_PASSWORD)
    account.text_input(key="new_password").input(NEW_PASSWORD)
    account.text_input(key="repeat_password").input(NEW_PASSWORD)
    _click(account, "Change password")
    assert not account.exception
    assert any("password has been changed" in s.value for s in account.success)
    at.run()
    assert at.number_input  # the check page opens now


def test_change_password_errors(app_path) -> None:
    at = open_page(ACCOUNT, role=auth.APPLICANT).run()
    at.text_input(key="current_password").input("wrong-password-1")
    at.text_input(key="new_password").input(NEW_PASSWORD)
    at.text_input(key="repeat_password").input(NEW_PASSWORD)
    _click(at, "Change password")
    assert any("current password is not correct" in e.value for e in at.error)
    at.text_input(key="current_password").input(TEST_PASSWORD)
    at.text_input(key="new_password").input(NEW_PASSWORD)
    at.text_input(key="repeat_password").input(NEW_PASSWORD + "x")
    _click(at, "Change password")
    assert any("do not match" in e.value for e in at.error)
    at.text_input(key="current_password").input(TEST_PASSWORD)
    at.text_input(key="new_password").input("password123")
    at.text_input(key="repeat_password").input("password123")
    _click(at, "Change password")
    assert any("too common" in e.value for e in at.error)


def test_delete_account_needs_confirmation(app_path) -> None:
    session = new_session()
    at = open_page(ACCOUNT, session=session).run()
    at.text_input(key="delete_password").input(TEST_PASSWORD)
    _click(at, "Delete my account")
    assert any("Tick the box" in e.value for e in at.error)
    at.checkbox(key="delete_confirm").check()
    at.text_input(key="delete_password").input("wrong-password-1")
    _click(at, "Delete my account")
    assert any("not correct" in e.value for e in at.error)
    at.checkbox(key="delete_confirm").check()
    at.text_input(key="delete_password").input(TEST_PASSWORD)
    _click(at, "Delete my account")
    assert not at.exception and not _signed_in(at)
    assert any("account has been deleted" in w.value for w in at.warning)
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(session.principal.email, TEST_PASSWORD)


# ---- Users page ------------------------------------------------------------------------------


def test_users_page_lists_accounts(app_path) -> None:
    manager = new_session(auth.MANAGER)
    applicant = new_session()
    at = open_page(USERS, session=manager).run()
    assert not at.exception
    table = at.dataframe[0].value
    assert list(table.columns) == ["Email", "Role", "Status", "Created", "Last sign-in"]
    assert set(table["Email"]) == {manager.principal.email, applicant.principal.email}
    assert set(table["Role"]) == {"Bank manager", "Applicant"}
    assert "password" not in " ".join(table.columns).lower()


def test_users_page_create_manager(app_path) -> None:
    manager = new_session(auth.MANAGER)
    at = open_page(USERS, session=manager).run()
    email = new_email(auth.MANAGER)
    at.text_input(key="new_manager_email").input(email)
    at.text_input(key="new_manager_password").input(NEW_PASSWORD)
    at.text_input(key="new_manager_repeat").input(NEW_PASSWORD)
    _click(at, "Create manager")
    assert not at.exception
    assert any("manager account was created" in s.value for s in at.success)
    assert email in set(at.dataframe[0].value["Email"])
    at.text_input(key="new_manager_email").input(new_email())
    at.text_input(key="new_manager_password").input("password123")
    at.text_input(key="new_manager_repeat").input("password123")
    _click(at, "Create manager")
    assert any("too common" in e.value for e in at.error)


def test_users_page_deactivate_and_reset(app_path) -> None:
    manager = new_session(auth.MANAGER)
    applicant = new_session()
    at = open_page(USERS, session=manager).run()
    at.selectbox(key="status_user").set_value(applicant.principal.user_id).run()
    at.button(key="toggle_active").click().run()
    assert any("deactivated" in s.value for s in at.success)
    with pytest.raises(auth.LoginFailed):
        auth.sign_in(applicant.principal.email, TEST_PASSWORD)
    assert at.button(key="toggle_active").label == "Reactivate"
    at.button(key="toggle_active").click().run()
    assert any("reactivated" in s.value for s in at.success)
    at.selectbox(key="reset_user").set_value(applicant.principal.user_id)
    at.text_input(key="reset_password").input(NEW_PASSWORD)
    at.text_input(key="reset_repeat").input(NEW_PASSWORD)
    _click(at, "Set temporary password")
    assert any("temporary password was set" in s.value for s in at.success)
    assert auth.sign_in(applicant.principal.email, NEW_PASSWORD).principal.must_change_password


def test_users_page_with_no_other_accounts(app_path) -> None:
    at = open_page(USERS, role=auth.MANAGER).run()
    assert any("no other accounts" in i.value for i in at.info)
