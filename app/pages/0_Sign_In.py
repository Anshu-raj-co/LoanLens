"""Sign in, or create an applicant account. Manager accounts cannot be created here."""

from __future__ import annotations

import streamlit as st
from ui_common import (
    NOTICE_KEY,
    current_principal,
    end_session,
    escape_md,
    footer,
    page_link,
    setup_page,
    start_session,
)

from loanlens import auth
from loanlens.auth import passwords
from loanlens.db.engine import DatabaseError

setup_page("Sign in")

principal = current_principal()
if principal is not None:
    st.success(f"You are signed in as **{escape_md(principal.email)}** ({principal.role_label}).")
    page_link("pages/1_Check_My_Eligibility.py", "Check my eligibility")
    page_link("pages/7_My_History.py", "My history")
    if principal.is_manager:
        page_link("pages/2_Bulk_Check.py", "Bulk check")
        page_link("pages/8_Audit.py", "Audit")
        page_link("pages/5_Users.py", "Users")
    page_link("pages/6_Account.py", "Account")
    st.button("Sign out", key="sign_out_main", on_click=end_session)
    footer()
    st.stop()

notice = st.session_state.pop(NOTICE_KEY, None)
if notice:
    st.info(notice)

settings = auth.load_settings()
tab_in, tab_up = st.tabs(["Sign in", "Create account"])

with tab_in:
    with st.form("sign_in_form", clear_on_submit=True):
        email = st.text_input("Email", key="signin_email", autocomplete="email")
        password = st.text_input(
            "Password", type="password", key="signin_password", autocomplete="current-password"
        )
        submitted = st.form_submit_button("Sign in", type="primary")
    st.caption(
        f"After {settings.lockout_attempts} wrong passwords in a row the account is locked for "
        f"{settings.lockout_minutes} minutes. Forgotten your password? Ask a bank manager to "
        "set a temporary one (there is no email reset)."
    )
    if submitted:
        try:
            start_session(auth.sign_in(email, password))
        except auth.LoginFailed:
            st.error(auth.GENERIC_LOGIN_ERROR)
        except DatabaseError as exc:
            st.error(str(exc))
        else:
            st.rerun()

with tab_up:
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
        created = st.form_submit_button("Create account", type="primary")
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
        else:
            try:
                start_session(auth.register_applicant(new_email, new_password))
            except auth.InputError as exc:
                for problem in exc.problems:
                    st.error(problem)
            except auth.AccountError as exc:
                st.error(str(exc))
            except DatabaseError as exc:
                st.error(str(exc))
            else:
                st.rerun()

footer()
