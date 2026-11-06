"""Helpers for page tests: open a Streamlit page as a signed-in applicant or manager."""

from __future__ import annotations

import secrets
import uuid

from loanlens import auth
from loanlens.cleaning import PROJECT_ROOT

APP_DIR = PROJECT_ROOT / "app"
TOKEN_KEY = "auth_token"
# Generated per test run, never stored.
TEST_PASSWORD = "Pw-" + secrets.token_urlsafe(12)

# The role each page needs ("auto" in open_page); public pages need none.
PAGE_ROLES = {
    "pages/1_Check_My_Eligibility.py": auth.APPLICANT,
    "pages/2_Bulk_Check.py": auth.MANAGER,
    "pages/3_Analytics.py": auth.MANAGER,
    "pages/5_Users.py": auth.MANAGER,
    "pages/6_Account.py": auth.APPLICANT,
}


def new_email(role: str = auth.APPLICANT) -> str:
    return f"{role}-{uuid.uuid4().hex[:10]}@example.com"


def new_session(
    role: str = auth.APPLICANT,
    email: str | None = None,
    password: str = TEST_PASSWORD,
    must_change_password: bool = False,
) -> auth.SignedIn:
    """Create an account with ``role`` in the test database and sign it in."""
    email = email or new_email(role)
    if role == auth.MANAGER:
        auth.create_manager_account(email, password, must_change_password=must_change_password)
        return auth.sign_in(email, password)
    signed_in = auth.register_applicant(email, password)
    return signed_in


def open_page(page: str, role: str | None = "auto", session: auth.SignedIn | None = None):
    """An AppTest for ``page`` (not yet run), signed in with ``role`` or ``session``.

    ``role="auto"`` uses the role the page needs (none for public pages); ``None`` opens
    the page signed out.
    """
    import sys

    from streamlit.testing.v1 import AppTest

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    at = AppTest.from_file(str(APP_DIR / page), default_timeout=120)
    if role == "auto":
        role = PAGE_ROLES.get(page)
    if session is None and role is not None:
        session = new_session(role)
    if session is not None:
        at.session_state[TOKEN_KEY] = session.token
    return at
