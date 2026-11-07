"""My History (any signed-in user): your own past checks, with CSV export."""

from __future__ import annotations

import streamlit as st
from ui_common import footer, get_policy, require_user, setup_page

from loanlens import auth, services
from loanlens.db.engine import DatabaseError
from loanlens.presentation import history_frame

setup_page("My History", "Every check you have made while signed in, newest first.")
principal = require_user()
policy = get_policy()

st.caption(
    "Every check you make on Check My Eligibility while signed in is listed here, newest "
    "first. Only you can see your history. The records hold the details you entered, the "
    "result and the versions used, never your email address or name."
)

try:
    items = services.my_history(principal)
except auth.AuthorisationError as exc:
    st.error(f"{exc} Open Sign In from the menu.")
    footer()
    st.stop()
except DatabaseError as exc:
    st.error(str(exc))
    footer()
    st.stop()

if not items:
    st.info(
        "You have not made any checks yet. Open **Check My Eligibility** to make one.",
        icon=":material/history:",
    )
    footer()
    st.stop()

table = history_frame(items, policy.display.probability_bands)
approved = int((table["Status"] == "Approved").sum())
columns = st.columns(3)
figures = [("Checks", len(table)), ("Approved", approved), ("Rejected", len(table) - approved)]
tones = {"Approved": "approved", "Rejected": "rejected", "Borderline": "warning"}
for i, (col, (label, value)) in enumerate(zip(columns, figures, strict=True)):
    with col, st.container(key=f"kpi_{tones.get(label, 'primary')}_{i}"):
        st.metric(label, f"{value:,}")
st.dataframe(table, hide_index=True, use_container_width=True)
st.download_button(
    "Download my history (CSV)",
    data=table.to_csv(index=False).encode("utf-8"),
    file_name="loanlens_my_history.csv",
    mime="text/csv",
    icon=":material/download:",
)
footer()
