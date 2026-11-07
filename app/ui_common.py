"""Shared look, navigation, session and safety helpers for every LoanLens page (layout only).

Navigation: ``app/Home.py`` is the entry point. On every run it re-validates the session,
builds the menu for the signed-in role with ``st.navigation`` and runs the chosen page
(:func:`run_app`). Signed-out visitors get only the Sign In page and no menu.

Sessions: the signed token and the principal live in ``st.session_state``. The token is
re-validated against the accounts database on every run (signature, expiry, account still
active, same role), so an expired or invalid session sends the user back to Sign In. All
account logic is in :mod:`loanlens.auth`; the menu is a convenience, and every page still
checks the role itself (:func:`require_user`).
"""

from __future__ import annotations

import html
import os
import re
import runpy
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
APP_DIR = Path(__file__).resolve().parent
ASSETS = APP_DIR / "assets"
LOGO_MARK = ASSETS / "logo_mark.svg"
LOGO_WORDMARK = ASSETS / "logo_wordmark.svg"
SIGN_IN_PAGE = "pages/0_Sign_In.py"
ACCOUNT_PAGE = "pages/6_Account.py"
TOKEN_KEY = "auth_token"
PRINCIPAL_KEY = "auth_principal"
NOTICE_KEY = "auth_notice"
SIGNED_OUT = "You have signed out."
SECURITY_NOTICE_TITLE = "Security notice: temporary signing key"

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$])")


# ---- Pages and navigation --------------------------------------------------------------------


@dataclass(frozen=True)
class PageSpec:
    """One page of the app: its file, menu title, Material icon, URL and Home card text."""

    path: str
    title: str
    icon: str
    url: str
    blurb: str = ""


PAGES: dict[str, PageSpec] = {
    "sign_in": PageSpec(SIGN_IN_PAGE, "Sign In", ":material/login:", "sign-in"),
    "home": PageSpec("pages/9_Home.py", "Home", ":material/space_dashboard:", "home"),
    "check": PageSpec(
        "pages/1_Check_My_Eligibility.py", "Check My Eligibility", ":material/fact_check:",
        "check", "Enter your details and get an instant result with plain-language reasons.",
    ),
    "bulk": PageSpec(
        "pages/2_Bulk_Check.py", "Bulk Check", ":material/upload_file:", "bulk-check",
        "Upload a CSV or Parquet file of many applicants and download every result.",
    ),
    "analytics": PageSpec(
        "pages/3_Analytics.py", "Analytics", ":material/insights:", "analytics",
        "Approval patterns in the training data, model drivers and the latest batch.",
    ),
    "audit": PageSpec(
        "pages/8_Audit.py", "Audit", ":material/policy:", "audit",
        "The append-only record of every decision, with filters and CSV export.",
    ),
    "users": PageSpec(
        "pages/5_Users.py", "Users", ":material/group:", "users",
        "Create manager accounts, deactivate accounts and set temporary passwords.",
    ),
    "history": PageSpec(
        "pages/7_My_History.py", "My History", ":material/history:", "my-history",
        "Every check you have made while signed in, with a CSV download.",
    ),
    "account": PageSpec(
        "pages/6_Account.py", "Account", ":material/manage_accounts:", "account",
        "Change your password or delete your account.",
    ),
    "about": PageSpec(
        "pages/4_About.py", "About", ":material/info:", "about",
        "Data source, model card, metrics, limitations and policy settings.",
    ),
}  # fmt: skip

SIGNED_OUT_NAV = ["sign_in"]
APPLICANT_NAV = ["home", "check", "history", "account", "about"]
MANAGER_NAV = ["home", "check", "bulk", "analytics", "audit", "users", "history", "account",
               "about"]  # fmt: skip
PASSWORD_CHANGE_NAV = ["account"]
NAV_SECTIONS = {  # menu section -> page keys (pages a role cannot open are left out)
    "Workspace": ["home", "check", "history"],
    "Bank manager": ["bulk", "analytics", "audit", "users"],
    "Account": ["account", "about"],
}


def nav_keys(principal: auth.Principal | None) -> list[str]:
    """The pages in the menu for this user, default page first.

    Signed out: Sign In only. A user who must change a temporary password: Account only.
    The stored role decides; this list is navigation only (every page re-checks the role).
    """
    if principal is None:
        return list(SIGNED_OUT_NAV)
    if principal.must_change_password:
        return list(PASSWORD_CHANGE_NAV)
    return list(MANAGER_NAV if principal.is_manager else APPLICANT_NAV)


def home_cards(principal: auth.Principal) -> list[str]:
    """The Home feature cards for this user: every page in their menu except Home itself."""
    return [k for k in nav_keys(principal) if k not in ("home", "sign_in")]


def _page_runner(key: str) -> Any:
    """A callable that runs one page file (the file keeps its path in app/pages/)."""
    path = APP_DIR / PAGES[key].path

    def run() -> None:
        runpy.run_path(str(path), run_name="__page__")

    run.__name__ = f"page_{key}"
    return run


def _st_page(key: str, default: bool = False) -> Any:
    """``st.Page`` for a page file, run through a callable.

    Streamlit 1.40 runs a callable page the same way in the server and in ``AppTest``,
    while a file-path page does not run inside ``AppTest`` (decisions log).
    """
    spec = PAGES[key]
    return st.Page(_page_runner(key), title=spec.title, icon=spec.icon, url_path=spec.url,
                   default=default)  # fmt: skip


def _sections(keys: list[str], pages: dict[str, Any]) -> dict[str, list[Any]] | list[Any]:
    if len(keys) == 1:
        return [pages[keys[0]]]
    grouped = {
        name: [pages[k] for k in members if k in pages] for name, members in NAV_SECTIONS.items()
    }
    return {name: items for name, items in grouped.items() if items}


def _redirect_if_not_allowed(pages: list[Any], default: Any) -> None:
    """Send a request for a page outside this user's menu to their default page.

    Without this, Streamlit shows a "page not found" notice before running the default page
    (after signing in or out, when a session ends, or for a typed URL). Reads Streamlit's
    request details; if they are not available, Streamlit's own fallback applies.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        manager = get_script_run_ctx().pages_manager
        wanted_hash = manager.intended_page_script_hash
        wanted_name = manager.intended_page_name
        hashes = {p._script_hash for p in pages}  # noqa: SLF001 - no public accessor
        names = {p.url_path for p in pages}
    except Exception:  # noqa: BLE001 - fall back to Streamlit's own handling
        return
    if (wanted_hash and wanted_hash not in hashes) or (
        not wanted_hash and wanted_name and wanted_name not in names
    ):
        st.switch_page(default)


# ---- Per-run state ---------------------------------------------------------------------------
# Each browser session runs its script in its own thread, so this is per run.
_RUN = threading.local()


def _in_entry() -> bool:
    """True while a page runs inside the navigation entry point (app/Home.py)."""
    return bool(getattr(_RUN, "entry", False))


@contextmanager
def _entry_run() -> Iterator[None]:
    _RUN.entry = True
    try:
        yield
    finally:
        _RUN.entry = False


def config_warnings() -> list[str]:
    """Hosted-mode configuration warnings found on this run (shown to everyone)."""
    return list(getattr(_RUN, "warnings", []))


def signing_key_is_temporary() -> bool:
    """True when no LOANLENS_JWT_SECRET is set and a temporary key is in use (development)."""
    return bool(getattr(_RUN, "ephemeral", False))


# ---- Look -----------------------------------------------------------------------------------


def escape_md(text: str) -> str:
    """Escape Markdown characters (emails and other user text are shown literally)."""
    return _MD_SPECIAL.sub(lambda m: "\\" + m.group(1), text)


def apply_theme() -> None:
    """Inject the shared design system (fonts, tokens, components). Called on every run."""
    st.markdown(css_block(), unsafe_allow_html=True)


def _page_config(title: str, signed_in: bool) -> None:
    st.set_page_config(
        page_title=f"{title} | {APP_NAME}",
        page_icon=str(LOGO_MARK),
        layout="wide",
        # "auto": open on wide screens, folded away on phones.
        initial_sidebar_state="auto" if signed_in else "collapsed",
    )


def _logo() -> None:
    try:
        st.logo(str(LOGO_WORDMARK), icon_image=str(LOGO_MARK))
    except Exception:  # noqa: BLE001 - the logo is decoration only
        pass


def page_header(title: str, subtitle: str | None = None) -> None:
    """The brand row, the page title and an optional one-line subtitle."""
    st.markdown(header_html(APP_NAME), unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        with st.container(key="page_subtitle"):
            st.markdown(subtitle)


def footer() -> None:
    """Disclaimer footer shown at the bottom of every page."""
    with st.container(key="page_footer"):
        st.caption(f"**{PROTOTYPE_NOTICE}.** {DISCLAIMER}")


# ---- Entry point and page set-up -------------------------------------------------------------


def run_app() -> None:
    """The navigation entry point: validate the session, build the role's menu, run a page."""
    problem = None
    try:
        _check_configuration()
    except auth.ConfigurationError as exc:
        problem = f"LoanLens cannot start. {exc}"
    principal = None if problem else _validate_session()
    keys = nav_keys(principal)
    pages = {k: _st_page(k, default=(i == 0)) for i, k in enumerate(keys)}
    default = pages[keys[0]]
    _RUN.pages = pages
    _redirect_if_not_allowed(list(pages.values()), default)
    nav = st.navigation(_sections(keys, pages), position="sidebar" if principal else "hidden")
    _page_config(nav.title, principal is not None)
    apply_theme()
    if problem:
        st.error(problem)
        st.stop()
    if principal is not None:
        _logo()
        with st.sidebar:
            sidebar_account(principal)
    with _entry_run():
        nav.run()


def setup_page(title: str, subtitle: str | None = None, *, header: bool = True) -> None:
    """Page header for every page (``header=False`` for pages with their own hero). Call first.

    Inside the entry point the page config, theme, session check and sidebar are already
    done. A page run on its own (tests, or ``streamlit run app/pages/...``) does them here.
    """
    if not _in_entry():
        _page_config(title, True)
        apply_theme()
        try:
            _check_configuration()
        except auth.ConfigurationError as exc:
            st.error(f"LoanLens cannot start. {exc}")
            st.stop()
            raise  # pragma: no cover - st.stop() ends the script
        principal = _validate_session()
        if principal is not None:
            with st.sidebar:
                sidebar_account(principal)
    if header:
        page_header(title, subtitle)


def _streamlit_secrets() -> dict[str, Any]:
    """Top-level Streamlit secrets (hosted platforms), or nothing when none are configured."""
    try:
        if not st.secrets.load_if_toml_exists():  # no secrets file: the normal local case
            return {}
        return {name: st.secrets[name] for name in st.secrets}
    except Exception:  # noqa: BLE001 - a malformed secrets file is ignored here
        return {}


def _check_configuration() -> None:
    """Apply secrets and check the settings; raise ``auth.ConfigurationError`` on a problem.

    Records for this run whether the signing key is temporary and any hosted-mode warnings.
    """
    _RUN.ephemeral, _RUN.warnings = False, []
    hosted.apply_secrets(_streamlit_secrets(), os.environ)
    key = auth.signing_key()
    auth.load_settings()
    _RUN.warnings = hosted.check_settings()
    _RUN.ephemeral = key.ephemeral
    try:
        auth.bootstrap_from_env()
    except Exception:  # noqa: BLE001 - a database problem is reported when it is used
        pass


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
    """The signed-in user for this run (validated by :func:`run_app` or :func:`setup_page`)."""
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


# ---- Sidebar ---------------------------------------------------------------------------------


def sidebar_account(principal: auth.Principal) -> None:
    """The signed-in user card: avatar initial, email, role and a Sign out button."""
    initial = (principal.email[:1] or "?").upper()
    with st.container(key="user_card"):
        st.markdown(
            f'<span class="ll-avatar" aria-hidden="true">{html.escape(initial)}</span>',
            unsafe_allow_html=True,
        )
        st.markdown(f"**{escape_md(principal.email)}**")
        st.caption(f"Role: {principal.role_label}")
        st.button("Sign out", key="sign_out", on_click=end_session, icon=":material/logout:",
                  use_container_width=True)  # fmt: skip
    for warning in config_warnings():
        st.warning(warning)
    st.caption(PROTOTYPE_NOTICE)


def security_notice(principal: auth.Principal) -> None:
    """For managers only: the temporary-signing-key notice, collapsed (development only)."""
    if principal.is_manager and signing_key_is_temporary():
        with st.expander(SECURITY_NOTICE_TITLE, icon=":material/shield:"):
            st.warning(auth_settings.EPHEMERAL_WARNING)


def page_link(key: str, label: str, icon: str | None = None) -> None:
    """A link to a page in this user's menu (``key`` from :data:`PAGES`).

    Outside the entry point, or for a page that is not in the menu, it is plain text.
    """
    page = getattr(_RUN, "pages", {}).get(key) if _in_entry() else None
    if page is None:
        st.markdown(f"Open **{label}** from the menu.")
        return
    st.page_link(page, label=label, icon=icon)


def require_user(*roles: str, allow_password_change: bool = False) -> auth.Principal:
    """The signed-in principal with one of ``roles`` (any role if none), else stop the page.

    Without a session the page shows a plain message and a link to Sign In. A user who must
    change their password is sent to the Account page first.
    """
    principal = current_principal()
    notice = st.session_state.pop(NOTICE_KEY, None)
    if principal is None:
        if notice:
            st.warning(notice)
        st.info("Please sign in to use this page.")
        page_link("sign_in", "Go to Sign In", ":material/login:")
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
        page_link("account", "Go to Account", ":material/manage_accounts:")
        footer()
        st.stop()
    return principal


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
