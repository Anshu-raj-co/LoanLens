"""Shared look, session and safety helpers for every LoanLens page (layout only).

Sessions: the signed token and the principal live in ``st.session_state``. The token is
re-validated against the accounts database on every page load (signature, expiry, account
still active, same role), so an expired or invalid session sends the user back to Sign in.
All account logic is in :mod:`loanlens.auth`.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st

# The app also runs from a plain clone without installing the package (for example on a
# hosted platform that only installs requirements.txt): put src/ on the import path then.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    try:
        import loanlens  # noqa: F401 - installed (normal, editable or in Docker)
    except ImportError:
        sys.path.insert(0, str(_SRC))

from loanlens import auth, hosted, registry  # noqa: E402
from loanlens import model as model_mod  # noqa: E402
from loanlens.auth import settings as auth_settings  # noqa: E402
from loanlens.auth.service import DATABASE_MESSAGE, SESSION_ENDED  # noqa: E402
from loanlens.config import Policy, load_policy  # noqa: E402
from loanlens.presentation import DISCLAIMER, PROTOTYPE_NOTICE  # noqa: E402
from loanlens.theme import css_block, header_html  # noqa: E402

APP_NAME = "LoanLens"
SIGN_IN_PAGE = "pages/0_Sign_In.py"
ACCOUNT_PAGE = "pages/6_Account.py"
TOKEN_KEY = "auth_token"
PRINCIPAL_KEY = "auth_principal"
NOTICE_KEY = "auth_notice"
SIGNED_OUT = "You have signed out."

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$])")


def escape_md(text: str) -> str:
    """Escape Markdown characters (emails and other user text are shown literally)."""
    return _MD_SPECIAL.sub(lambda m: "\\" + m.group(1), text)


def setup_page(title: str) -> None:
    """Page config, configuration check, session check, sidebar and title. Call first."""
    st.set_page_config(page_title=f"{APP_NAME} | {title}", layout="wide")
    st.markdown(css_block(), unsafe_allow_html=True)
    st.markdown(header_html(APP_NAME), unsafe_allow_html=True)
    ephemeral, warnings = _check_configuration()
    principal = _validate_session()
    with st.sidebar:
        st.markdown(f"### {APP_NAME}")
        st.caption("Explainable loan pre-eligibility prototype")
        st.caption(PROTOTYPE_NOTICE)
        _sidebar_account(principal)
        if ephemeral:
            st.warning(auth_settings.EPHEMERAL_WARNING)
        for warning in warnings:
            st.warning(warning)
    st.title(title)


def _streamlit_secrets() -> dict[str, Any]:
    """Top-level Streamlit secrets (hosted platforms), or nothing when none are configured."""
    try:
        if not st.secrets.load_if_toml_exists():  # no secrets file: the normal local case
            return {}
        return {name: st.secrets[name] for name in st.secrets}
    except Exception:  # noqa: BLE001 - a malformed secrets file is ignored here
        return {}


def _check_configuration() -> tuple[bool, list[str]]:
    """Stop with a clear message on a configuration error.

    Returns whether the signing key is temporary and any warnings for the sidebar.
    """
    hosted.apply_secrets(_streamlit_secrets(), os.environ)
    try:
        key = auth.signing_key()
        auth.load_settings()
        warnings = hosted.check_settings()
    except auth.ConfigurationError as exc:
        st.error(f"LoanLens cannot start. {exc}")
        st.stop()
        raise  # pragma: no cover - st.stop() ends the script
    try:
        auth.bootstrap_from_env()
    except Exception:  # noqa: BLE001 - a database problem is reported when it is used
        pass
    return key.ephemeral, warnings


def _clear_session() -> None:
    for name in list(st.session_state.keys()):
        del st.session_state[name]


def _validate_session() -> auth.Principal | None:
    """Re-validate the stored token; on failure clear the session and leave a notice."""
    token = st.session_state.get(TOKEN_KEY)
    if not token:
        st.session_state.pop(PRINCIPAL_KEY, None)
        return None
    try:
        principal = auth.principal_from_token(token)
    except auth.InvalidSession:
        _clear_session()
        st.session_state[NOTICE_KEY] = SESSION_ENDED
        return None
    except Exception:  # noqa: BLE001 - database down: treat as signed out, explain why
        _clear_session()
        st.session_state[NOTICE_KEY] = DATABASE_MESSAGE
        return None
    st.session_state[PRINCIPAL_KEY] = principal
    return principal


def current_principal() -> auth.Principal | None:
    """The signed-in user for this page load (validated by :func:`setup_page`)."""
    return st.session_state.get(PRINCIPAL_KEY)


def start_session(signed_in: auth.SignedIn) -> None:
    """Keep a new session's token and principal in session state."""
    st.session_state.pop(NOTICE_KEY, None)
    st.session_state[TOKEN_KEY] = signed_in.token
    st.session_state[PRINCIPAL_KEY] = signed_in.principal


def end_session(notice: str = SIGNED_OUT) -> None:
    """Record the sign-out and clear everything this browser session held."""
    principal = current_principal()
    try:
        auth.sign_out(principal)
    except Exception:  # noqa: BLE001 - signing out must always work
        pass
    _clear_session()
    st.session_state[NOTICE_KEY] = notice


def _sidebar_account(principal: auth.Principal | None) -> None:
    st.divider()
    if principal is None:
        st.caption("Not signed in.")
        page_link(SIGN_IN_PAGE, "Sign in or create an account")
        return
    st.markdown(f"Signed in as **{escape_md(principal.email)}**")
    st.caption(f"Role: {principal.role_label}")
    st.button("Sign out", key="sign_out", on_click=end_session)


def page_link(page: str, label: str) -> None:
    """A link to another page (plain text if the page cannot be linked in this context)."""
    try:
        st.page_link(page, label=label)
    except Exception:  # noqa: BLE001 - e.g. a page run on its own in a test harness
        st.markdown(f"Open **{label}** from the menu on the left.")


def require_user(*roles: str, allow_password_change: bool = False) -> auth.Principal:
    """The signed-in principal with one of ``roles`` (any role if none), else stop the page.

    Without a session the page shows a plain message and a link to Sign in. A user who must
    change their password is sent to the Account page first.
    """
    principal = current_principal()
    notice = st.session_state.pop(NOTICE_KEY, None)
    if principal is None:
        if notice:
            st.warning(notice)
        st.info("Please sign in to use this page.")
        page_link(SIGN_IN_PAGE, "Go to Sign in")
        footer()
        st.stop()
    try:
        auth.require_role(principal, *roles)
    except auth.PermissionDenied as exc:
        st.info(f"{exc} You are signed in as: {principal.role_label}.")
        footer()
        st.stop()
    if principal.must_change_password and not allow_password_change:
        st.warning("You must choose a new password before you can continue.")
        page_link(ACCOUNT_PAGE, "Go to Account")
        footer()
        st.stop()
    return principal


def footer() -> None:
    """Disclaimer footer shown at the bottom of every page."""
    st.divider()
    st.caption(f"**{PROTOTYPE_NOTICE}.** {DISCLAIMER}")


def get_policy() -> Policy:
    """Load the policy file, or stop the page with a friendly message."""
    try:
        return load_policy()
    except Exception:  # noqa: BLE001 - never show a stack trace to the user
        st.error(
            "The policy settings files (config/policies/) could not be read. "
            "Please ask the administrator to check it."
        )
        footer()
        st.stop()
        raise  # pragma: no cover - st.stop() ends the script


@st.cache_resource(show_spinner="Loading the model...")
def _cached_artifact() -> dict[str, Any]:
    return model_mod.load_artifact()


def get_model() -> dict[str, Any]:
    """Load (once per server) the trained model, or stop with a friendly message."""
    try:
        return _cached_artifact()
    except FileNotFoundError:
        st.error(
            "The prediction model has not been trained yet, so results cannot be shown. "
            "Ask the administrator to run `python -m loanlens.model` and reload this page."
        )
    except registry.RegistryError as exc:  # plain message, e.g. a fingerprint mismatch
        st.error(f"The prediction model could not be loaded. {exc}")
    except Exception:  # noqa: BLE001
        st.error(
            "The prediction model could not be loaded. Ask the administrator to retrain it "
            "with `python -m loanlens.model`."
        )
    footer()
    st.stop()
    raise RuntimeError  # pragma: no cover - st.stop() ends the script


def friendly_failure(context: str) -> None:
    """Show a generic friendly error (used in place of a stack trace)."""
    st.error(
        f"Sorry, something went wrong while {context}. Please check the inputs and try again. "
        "If the problem continues, contact the LoanLens administrator."
    )
