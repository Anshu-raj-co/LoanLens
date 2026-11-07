"""Sign In: the first screen. A role selector, then sign in (or create an applicant account).

The role selector is a convenience, not a permission: the account's stored role decides. A
correct password for an account of the other role starts no session (the sign-out is
recorded and the token is dropped) and shows a neutral message. Wrong credentials always get
the same generic message. Manager accounts cannot be created here.
"""

from __future__ import annotations

import streamlit as st
from ui_common import (
    NOTICE_KEY,
    config_warnings,
    current_principal,
    end_session,
    escape_md,
    footer,
    setup_page,
    start_session,
)

from loanlens import auth
from loanlens.auth import passwords
from loanlens.db.engine import DatabaseError
from loanlens.presentation import PROTOTYPE_NOTICE
from loanlens.theme import brand_panel_html

APPLICANT_PORTAL = "Applicant"
MANAGER_PORTAL = "Bank manager (admin)"
PORTALS = [APPLICANT_PORTAL, MANAGER_PORTAL]
PORTAL_KEY = "portal"
MANAGER_NOTE = (
    "Bank manager accounts are created by an administrator or by another manager. They "
    "cannot be created here."
)
WRONG_PORTAL = {
    MANAGER_PORTAL: "This account is not a bank manager account. Choose Applicant to sign in.",
    APPLICANT_PORTAL: (
        "This account is a bank manager account. Choose Bank manager (admin) to sign in."
    ),
}
PORTAL_ROLE = {APPLICANT_PORTAL: auth.APPLICANT, MANAGER_PORTAL: auth.MANAGER}

setup_page("Sign In", header=False)

principal = current_principal()
if principal is not None:  # only reachable when this page is run on its own
    st.success(f"You are signed in as **{escape_md(principal.email)}** ({principal.role_label}).")
    st.button("Sign out", key="sign_out_main", on_click=end_session)
    footer()
    st.stop()


def _sign_in(email: str, password: str, portal: str) -> None:
    """Sign in with the unchanged auth service; keep the session only if the role matches."""
    try:
        signed_in = auth.sign_in(email, password)
    except auth.LoginFailed:
        st.error(auth.GENERIC_LOGIN_ERROR)
        return
    except DatabaseError as exc:
        st.error(str(exc))
        return
    if signed_in.principal.role != PORTAL_ROLE[portal]:
        try:
            auth.sign_out(signed_in.principal)  # records it; the token is never kept
        except Exception:  # noqa: BLE001 - the session is not kept either way
            pass
        del signed_in
        st.info(WRONG_PORTAL[portal])
        return
    start_session(signed_in)
    st.rerun()  # the menu is rebuilt and the user lands on Home


def _sign_in_form(settings, portal: str) -> None:
    with st.form("sign_in_form", clear_on_submit=True):
        email = st.text_input("Email", key="signin_email", autocomplete="email")
        password = st.text_input(
            "Password", type="password", key="signin_password", autocomplete="current-password"
        )
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        _sign_in(email, password, portal)
    st.caption(
        f"After {settings.lockout_attempts} wrong passwords in a row the account is locked for "
        f"{settings.lockout_minutes} minutes. Forgotten your password? Ask a bank manager to "
        "set a temporary one (there is no email reset)."
    )


def _create_account_form() -> None:
    st.markdown(
        "Create an **applicant** account to check your own eligibility. Bank manager "
        "accounts are created by an administrator, not here."
    )
    with st.form("sign_up_form", clear_on_submit=True):
        new_email = st.text_input("Email", key="signup_email", autocomplete="email")
        new_password = st.text_input(
            "Password", type="password", key="signup_password", autocomplete="new-password"
        )
        repeat = st.text_input(
            "Type the password again", type="password", key="signup_repeat",
            autocomplete="new-password",
        )  # fmt: skip
        created = st.form_submit_button("Create account", type="primary", use_container_width=True)
    st.caption(
        f"Passwords need {passwords.MIN_LENGTH} to {passwords.MAX_LENGTH} characters, must not "
        "be a common password and must not be your email address. A passphrase of a few "
        "unrelated words works well."
    )
    st.caption(
        "What is stored: your email address, a one-way scrambled form of your password (never "
        "the password itself), your role and the times you signed up and last signed in. "
        "Email addresses are not verified."
    )
    if created:
        if new_password != repeat:
            st.error("The two passwords do not match.")
            return
        try:
            start_session(auth.register_applicant(new_email, new_password))
        except auth.InputError as exc:
            for problem in exc.problems:
                st.error(problem)
        except (auth.AccountError, DatabaseError) as exc:
            st.error(str(exc))
        else:
            st.rerun()


settings = auth.load_settings()
notice = st.session_state.pop(NOTICE_KEY, None)

brand, card = st.columns([1, 1.05], gap="large", vertical_alignment="center")
with brand:
    st.markdown(
        brand_panel_html(
            "LoanLens",
            "Explainable loan pre-eligibility: a clear result, the reasons behind it and what "
            "would likely change it.",
            [
                "Plain-language reasons for every result",
                "Policy rules checked before the model",
                "Every decision kept in an audit trail",
            ],
        ),
        unsafe_allow_html=True,
    )
with card, st.container(key="signin_card"):
    st.markdown("### Sign in to LoanLens")
    st.caption(f"{PROTOTYPE_NOTICE}.")
    # A horizontal radio styled as a segmented control: Streamlit 1.40 has
    # st.segmented_control, but its single-select form cannot be driven by AppTest, so the
    # sign-in tests could not cover it (decisions log).
    portal = st.radio(
        "I am signing in as", PORTALS, key=PORTAL_KEY, horizontal=True,
        label_visibility="collapsed",
    )  # fmt: skip
    portal = portal if portal in PORTALS else APPLICANT_PORTAL
    if notice:
        st.info(notice)
    if portal == MANAGER_PORTAL:
        (tab_in,) = st.tabs(["Sign in"])
        with tab_in:
            st.caption(MANAGER_NOTE)
            _sign_in_form(settings, portal)
    else:
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            _sign_in_form(settings, portal)
        with tab_up:
            _create_account_form()

for warning in config_warnings():
    st.warning(warning)
footer()
