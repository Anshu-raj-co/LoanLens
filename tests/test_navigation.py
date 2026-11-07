"""Sign-in-first navigation: the menu per role, the role selector and the portal checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app_support import APP_DIR, TEST_PASSWORD, new_session, open_page

from loanlens import auth
from loanlens.auth import settings, tokens

ENTRY = "Home.py"
APPLICANT_PORTAL = "Applicant"
MANAGER_PORTAL = "Bank manager (admin)"
WRONG_PORTAL_FOR_MANAGER = "This account is not a bank manager account"
WRONG_PORTAL_FOR_APPLICANT = "This account is a bank manager account"


def _ui():
    import ui_common

    return ui_common


def _entry(session: auth.SignedIn | None = None):
    at = open_page(ENTRY, role=None, session=session)
    return at.run()


def _signed_in(at) -> bool:
    return "auth_token" in at.session_state and bool(at.session_state["auth_token"])


def _portal(at, choice: str):
    return at.radio(key="portal").set_value(choice).run()


def _sign_in(at, email: str, password: str):
    at.text_input(key="signin_email").input(email)
    at.text_input(key="signin_password").input(password)
    return next(b for b in at.button if b.label == "Sign in").click().run()


def _messages(at) -> list[str]:
    return [str(e.value) for kind in ("info", "warning", "error", "success") for e in at.get(kind)]


def _is_sign_in(at) -> bool:
    return any(r.key == "portal" for r in at.radio)


def _notice(at, title: str) -> list:
    """Expanders with ``title`` (AppTest lists an expander with an icon as "status")."""
    return [e for e in [*at.expander, *at.get("status")] if e.label == title]


def _is_home(at) -> bool:
    return any("ll-hero-body" in m.value for m in at.markdown)


# ---- Menu per role (navigation only; pages still check the role) -----------------------------


def test_nav_keys_per_role(app_path) -> None:
    ui = _ui()
    assert ui.nav_keys(None) == ["sign_in"]
    applicant = new_session().principal
    manager = new_session(auth.MANAGER).principal
    assert ui.nav_keys(applicant) == ["home", "check", "history", "account", "about"]
    assert ui.nav_keys(manager) == [
        "home", "check", "bulk", "analytics", "audit", "users", "history", "account", "about",
    ]  # fmt: skip
    manager_only = {"bulk", "analytics", "audit", "users"}
    assert not manager_only & set(ui.nav_keys(applicant))
    forced = new_session(auth.MANAGER, must_change_password=True).principal
    assert ui.nav_keys(forced) == ["account"]
    assert ui.home_cards(applicant) == ["check", "history", "account", "about"]
    assert len(ui.home_cards(manager)) == 8  # two full rows of four


def test_every_nav_page_exists(app_path) -> None:
    ui = _ui()
    for spec in ui.PAGES.values():
        assert (APP_DIR / spec.path).is_file(), spec.path
        assert spec.icon.startswith(":material/")
    sections = [k for keys in ui.NAV_SECTIONS.values() for k in keys]
    assert set(ui.MANAGER_NAV) == set(sections)


def test_signed_out_sees_only_sign_in(app_path) -> None:
    at = _entry()
    assert not at.exception
    assert _is_sign_in(at)
    assert [t.label for t in at.tabs] == ["Sign in", "Create account"]
    assert not at.sidebar.children  # no menu, no sidebar content
    assert not at.get("page_link")  # no feature links
    assert any("Prototype - not a lending decision" in c.value for c in at.caption)


def test_role_selector_defaults_to_applicant(app_path) -> None:
    at = _entry()
    selector = at.radio(key="portal")
    assert selector.options == [APPLICANT_PORTAL, MANAGER_PORTAL]
    assert selector.value == APPLICANT_PORTAL


def test_manager_portal_has_no_create_account(app_path) -> None:
    at = _portal(_entry(), MANAGER_PORTAL)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Sign in"]
    assert not any(b.label == "Create account" for b in at.button)
    assert any("cannot be created here" in c.value for c in at.caption)
    assert not at.text_input(key="signin_email").value  # nothing pre-filled


def test_applicant_signs_in_and_lands_on_home(app_path) -> None:
    email = new_session().principal.email
    at = _sign_in(_entry(), email, TEST_PASSWORD)
    assert not at.exception and _signed_in(at)
    assert _is_home(at)
    assert any("Role: Applicant" in c.value for c in at.sidebar.caption)
    links = " ".join(str(p.proto.page) for p in at.get("page_link"))
    assert "bulk-check" not in links and "audit" not in links and "users" not in links
    assert "check" in links and "my-history" in links


def test_manager_signs_in_on_manager_portal(app_path) -> None:
    email = new_session(auth.MANAGER).principal.email
    at = _sign_in(_portal(_entry(), MANAGER_PORTAL), email, TEST_PASSWORD)
    assert not at.exception and _signed_in(at)
    assert _is_home(at)
    links = " ".join(str(p.proto.page) for p in at.get("page_link"))
    for page in ("bulk-check", "analytics", "audit", "users", "my-history", "about"):
        assert page in links


def test_applicant_on_manager_portal_gets_no_session(app_path) -> None:
    email = new_session().principal.email
    at = _sign_in(_portal(_entry(), MANAGER_PORTAL), email, TEST_PASSWORD)
    assert not at.exception and not _signed_in(at)
    assert "auth_principal" not in at.session_state
    assert any(WRONG_PORTAL_FOR_MANAGER in m for m in _messages(at))
    assert _is_sign_in(at)


def test_manager_on_applicant_portal_gets_no_session(app_path) -> None:
    email = new_session(auth.MANAGER).principal.email
    at = _sign_in(_entry(), email, TEST_PASSWORD)
    assert not at.exception and not _signed_in(at)
    assert "auth_principal" not in at.session_state
    assert any(WRONG_PORTAL_FOR_APPLICANT in m for m in _messages(at))


@pytest.mark.parametrize("portal", [APPLICANT_PORTAL, MANAGER_PORTAL])
@pytest.mark.parametrize("role", [auth.APPLICANT, auth.MANAGER])
def test_wrong_credentials_show_only_the_generic_message(app_path, portal, role) -> None:
    email = new_session(role).principal.email
    at = _portal(_entry(), portal)
    at = _sign_in(at, email, "not-the-password")
    assert not at.exception and not _signed_in(at)
    assert [e.value for e in at.error] == [auth.GENERIC_LOGIN_ERROR]
    assert not any("bank manager account" in m for m in _messages(at))  # no role hint
    at = _sign_in(at, "nobody@example.com", TEST_PASSWORD)
    assert [e.value for e in at.error] == [auth.GENERIC_LOGIN_ERROR]


def test_wrong_portal_is_recorded_as_sign_out(app_path) -> None:
    from sqlalchemy import select

    from loanlens.auth import service
    from loanlens.db import models

    user = new_session().principal
    _sign_in(_portal(_entry(), MANAGER_PORTAL), user.email, TEST_PASSWORD)
    with service._db(None) as session:
        kinds = session.scalars(
            select(models.AuthEvent.event_type).where(models.AuthEvent.user_id == user.user_id)
        ).all()
    assert "sign_out" in kinds


def test_sign_out_returns_to_sign_in(app_path) -> None:
    at = _entry(new_session())
    assert _is_home(at)
    at.sidebar.button(key="sign_out").click().run()
    assert not at.exception and not _signed_in(at)
    assert _is_sign_in(at)
    assert any("You have signed out" in m for m in _messages(at))
    assert not at.sidebar.children


def test_expired_token_returns_to_sign_in(app_path) -> None:
    user = new_session().principal
    key = settings.signing_key().value
    old, _ = tokens.issue_token(user.user_id, user.role, key, 60,
                                now=datetime.now(UTC) - timedelta(hours=2))  # fmt: skip
    at = open_page(ENTRY, role=None)
    at.session_state["auth_token"] = old
    at.run()
    assert not at.exception and not _signed_in(at) and _is_sign_in(at)
    assert any("session has ended" in m for m in _messages(at))


def test_tampered_token_returns_to_sign_in(app_path) -> None:
    signed_in = new_session(auth.MANAGER)
    at = open_page(ENTRY, role=None)
    at.session_state["auth_token"] = signed_in.token[:-3] + "abc"
    at.run()
    assert not _signed_in(at) and _is_sign_in(at)
    assert any("session has ended" in m for m in _messages(at))


def test_forced_password_change_limits_navigation_to_account(app_path) -> None:
    session = new_session(auth.MANAGER, must_change_password=True)
    at = _entry(session)
    assert not at.exception
    assert any("must choose a new password" in m for m in _messages(at))
    assert at.text_input(key="current_password")  # the Account page runs
    assert not _is_home(at)
    assert not at.get("page_link")


def test_applicant_cannot_open_manager_page_by_url(app_path, artifact) -> None:
    at = _entry(new_session())
    at.switch_page("pages/2_Bulk_Check.py").run()
    assert not at.exception
    assert not at.get("file_uploader") and not at.dataframe
    assert _is_home(at)


def test_security_notice_only_for_managers(app_path, monkeypatch) -> None:
    monkeypatch.delenv(settings.ENV_SECRET)
    ui = _ui()
    signed_out = _entry()
    assert ui.SECURITY_NOTICE_TITLE not in str(signed_out._tree)
    assert "temporary signing key" not in " ".join(_messages(signed_out)).lower()
    applicant = open_page("pages/6_Account.py", role=auth.APPLICANT).run()
    assert not _notice(applicant, ui.SECURITY_NOTICE_TITLE)
    for page in ("pages/6_Account.py", "pages/5_Users.py"):
        at = open_page(page, role=auth.MANAGER).run()
        notice = _notice(at, ui.SECURITY_NOTICE_TITLE)
        assert notice, page
        assert any("temporary signing key" in w.value for w in notice[0].warning)
        assert not any("temporary signing key" in w.value for w in at.sidebar.warning)
