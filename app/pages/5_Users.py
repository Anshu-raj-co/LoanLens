"""Users page (bank managers): list accounts, create managers, deactivate, reset passwords."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from ui_common import footer, require_user, setup_page

from loanlens import auth
from loanlens.auth import passwords
from loanlens.db.engine import DatabaseError

setup_page("Users")
principal = require_user(auth.MANAGER)

message = st.session_state.pop("users_message", None)
if message:
    st.success(message)


def _when(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value is not None else "Never"


def _done(text: str) -> None:
    st.session_state["users_message"] = text
    st.rerun()


try:
    users = auth.list_users(principal)
except DatabaseError as exc:
    st.error(str(exc))
    footer()
    st.stop()

st.dataframe(
    pd.DataFrame(
        {
            "Email": [u.email for u in users],
            "Role": [auth.ROLE_LABELS[u.role] for u in users],
            "Status": [u.status for u in users],
            "Created": [_when(u.created_at) for u in users],
            "Last sign-in": [_when(u.last_login_at) for u in users],
        }
    ),
    hide_index=True,
    use_container_width=True,
)
st.caption(f"{len(users)} account(s). Passwords are stored only as argon2id hashes.")

others = {u.user_id: u for u in users if u.user_id != principal.user_id}


def _label(user_id: int) -> str:
    user = others[user_id]
    return f"{user.email} ({auth.ROLE_LABELS[user.role]}, {user.status})"


def _show_problems(exc: Exception) -> None:
    for problem in getattr(exc, "problems", None) or [str(exc)]:
        st.error(problem)


st.subheader("Create a manager")
with st.form("create_manager_form", clear_on_submit=True):
    email = st.text_input("Email", key="new_manager_email")
    temporary = st.text_input("Temporary password", type="password", key="new_manager_password")
    repeat = st.text_input("Type it again", type="password", key="new_manager_repeat")
    create = st.form_submit_button("Create manager", type="primary")
st.caption(
    f"The new manager must change this password at first sign-in. {passwords.MIN_LENGTH} to "
    f"{passwords.MAX_LENGTH} characters, not a common password, not the email address."
)
if create:
    if temporary != repeat:
        st.error("The two passwords do not match.")
    else:
        try:
            auth.create_manager(principal, email, temporary)
        except (auth.AuthError, DatabaseError) as exc:
            _show_problems(exc)
        else:
            _done("The manager account was created.")

if not others:
    st.info("There are no other accounts yet.")
    footer()
    st.stop()

st.subheader("Deactivate or reactivate an account")
st.caption("A deactivated account cannot sign in and any open session ends at once.")
target = st.selectbox("Account", list(others), format_func=_label, key="status_user")
is_active = others[target].is_active
if st.button("Deactivate" if is_active else "Reactivate", key="toggle_active"):
    try:
        auth.set_active(principal, target, not is_active)
    except (auth.AuthError, DatabaseError) as exc:
        _show_problems(exc)
    else:
        _done("The account was " + ("deactivated." if is_active else "reactivated."))

st.subheader("Set a temporary password")
st.caption(
    "Use this when someone has forgotten their password. They must choose a new one at their "
    "next sign-in. This also unlocks a locked account."
)
with st.form("reset_password_form", clear_on_submit=True):
    reset_target = st.selectbox("Account", list(others), format_func=_label, key="reset_user")
    reset_password = st.text_input("Temporary password", type="password", key="reset_password")
    reset_repeat = st.text_input("Type it again", type="password", key="reset_repeat")
    reset = st.form_submit_button("Set temporary password")
if reset:
    if reset_password != reset_repeat:
        st.error("The two passwords do not match.")
    else:
        try:
            auth.set_temporary_password(principal, reset_target, reset_password)
        except (auth.AuthError, DatabaseError) as exc:
            _show_problems(exc)
        else:
            _done("The temporary password was set. Give it to the user in person.")

footer()
