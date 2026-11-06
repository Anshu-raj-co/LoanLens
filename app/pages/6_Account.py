"""Account page for every signed-in user: change password, delete account."""

from __future__ import annotations

import streamlit as st
from ui_common import end_session, escape_md, footer, require_user, setup_page

from loanlens import auth
from loanlens.auth import passwords
from loanlens.db.engine import DatabaseError

setup_page("Account")
principal = require_user(allow_password_change=True)

st.markdown(f"Signed in as **{escape_md(principal.email)}**. Role: {principal.role_label}.")
if principal.must_change_password:
    st.warning(
        "You must choose a new password before you can use the other pages. Enter the "
        "temporary password you were given as the current password."
    )
if st.session_state.pop("account_message", None):
    st.success("Your password has been changed.")

st.subheader("Change password")
with st.form("change_password_form", clear_on_submit=True):
    current = st.text_input(
        "Current password", type="password", key="current_password",
        autocomplete="current-password",
    )  # fmt: skip
    new = st.text_input(
        "New password", type="password", key="new_password", autocomplete="new-password"
    )
    repeat = st.text_input(
        "Type the new password again", type="password", key="repeat_password",
        autocomplete="new-password",
    )  # fmt: skip
    change = st.form_submit_button("Change password", type="primary")
st.caption(
    f"{passwords.MIN_LENGTH} to {passwords.MAX_LENGTH} characters, not a common password and "
    "not your email address."
)
if change:
    if new != repeat:
        st.error("The two new passwords do not match.")
    else:
        try:
            auth.change_password(principal, current, new)
        except auth.InputError as exc:
            for problem in exc.problems:
                st.error(problem)
        except (auth.AccountError, DatabaseError) as exc:
            st.error(str(exc))
        else:
            st.session_state["account_message"] = "changed"
            st.rerun()

st.subheader("Delete account")
st.markdown(
    "Deleting your account removes your email address and password from LoanLens. Any "
    "records that were kept under your account's anonymous reference can then no longer be "
    "linked to you. This cannot be undone."
)
with st.form("delete_account_form", clear_on_submit=True):
    confirm = st.checkbox("I understand that this cannot be undone.", key="delete_confirm")
    password = st.text_input(
        "Password", type="password", key="delete_password", autocomplete="current-password"
    )
    delete = st.form_submit_button("Delete my account")
if delete:
    if not confirm:
        st.error("Tick the box to confirm that you want to delete your account.")
    else:
        try:
            auth.delete_own_account(principal, password)
        except (auth.AccountError, DatabaseError) as exc:
            st.error(str(exc))
        else:
            end_session("Your account has been deleted.")
            st.rerun()

footer()
