"""Audit (bank managers): the append-only decision audit trail with filters and CSV export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import streamlit as st
from pydantic import ValidationError
from ui_common import footer, require_user, setup_page

from loanlens import auth, services
from loanlens.audit import CHANNELS
from loanlens.db.engine import DatabaseError
from loanlens.presentation import AUDIT_NOTE, audit_frame, profile_label

PAGE_SIZE = 100
ANY = "Any"

setup_page("Audit")
principal = require_user(auth.MANAGER)
st.caption(AUDIT_NOTE)

try:
    options = services.audit_filter_options(principal)
except auth.AuthorisationError as exc:
    st.error(f"{exc} Open Sign in in the sidebar.")
    footer()
    st.stop()
except DatabaseError as exc:
    st.error(str(exc))
    footer()
    st.stop()

st.subheader("Filters")
today = datetime.now(UTC).date()
left, mid, right = st.columns(3)
with left:
    dates = st.date_input(
        "Date range (UTC)", value=(today - timedelta(days=30), today), key="audit_dates"
    )
    status = st.selectbox("Status", [ANY, "Approved", "Rejected"], key="audit_status")
with mid:
    profile = st.selectbox(
        "Loan type",
        [ANY, *options["profile"]],
        format_func=lambda p: p if p == ANY else profile_label(p),
        key="audit_profile",
    )
    channel = st.selectbox("Channel", [ANY, *CHANNELS], key="audit_channel")
with right:
    model_version = st.selectbox(
        "Model version", [ANY, *options["model_version"]], key="audit_model"
    )
    policy_version = st.selectbox(
        "Policy version", [ANY, *options["policy_version"]], key="audit_policy"
    )

if isinstance(dates, tuple | list):  # a range, or a single day while the range is being picked
    date_from = dates[0] if dates else None
    date_to = dates[1] if len(dates) > 1 else date_from
else:
    date_from = date_to = dates


def _value(choice: str) -> str | None:
    return None if choice == ANY else choice


try:
    filters = services.AuditFilters(
        date_from=date_from, date_to=date_to, status=_value(status), profile=_value(profile),
        channel=_value(channel), model_version=_value(model_version),
        policy_version=_value(policy_version),
    )  # fmt: skip
except ValidationError:
    st.error("Please choose a start date that is not after the end date.")
    footer()
    st.stop()

page_number = st.number_input("Page", min_value=1, value=1, step=1, key="audit_page")
try:
    page = services.audit_records(principal, filters, page=int(page_number), page_size=PAGE_SIZE)
except (auth.AuthorisationError, DatabaseError) as exc:
    st.error(str(exc))
    footer()
    st.stop()

counts = page.counts
cards = [
    ("Decisions", counts["total"]),
    ("Approved", counts["approved"]),
    ("Rejected", counts["rejected"]),
    ("Borderline", counts["borderline"]),
]
for col, (label, value) in zip(st.columns(len(cards)), cards, strict=True):
    with col:
        st.metric(label, f"{value:,}")

if not page.items:
    st.info("No decisions match these filters.")
    footer()
    st.stop()

pages = max(1, -(-page.total // PAGE_SIZE))
st.caption(f"Page {page.page} of {pages:,}, newest first ({page.total:,} matching records).")
st.dataframe(audit_frame(page.items), hide_index=True, use_container_width=True)

if st.button("Prepare CSV of all matching records", key="audit_prepare"):
    rows = services.audit_export(principal, filters)
    st.session_state["audit_csv"] = audit_frame(rows).to_csv(index=False).encode("utf-8")
if st.session_state.get("audit_csv"):
    st.download_button(
        "Download audit CSV",
        data=st.session_state["audit_csv"],
        file_name="loanlens_audit.csv",
        mime="text/csv",
    )
st.caption(f"The CSV holds up to {services.EXPORT_LIMIT:,} records.")
footer()
