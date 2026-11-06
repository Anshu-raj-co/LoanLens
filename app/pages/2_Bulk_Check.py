"""Bulk Check (bank managers only): upload a CSV, validate, score every applicant, download."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from ui_common import (
    footer,
    friendly_failure,
    get_model,
    get_policy,
    require_user,
    setup_page,
)

from loanlens import auth, batch, services
from loanlens.config import DEFAULT_PROFILE, list_profiles
from loanlens.db.engine import DatabaseError
from loanlens.formatting import SCORE_LABEL
from loanlens.presentation import PROTOTYPE_NOTICE, thresholds_note
from loanlens.theme import STYLED_ROWS_LIMIT, status_display_frame, style_status_column

setup_page("Bulk Check")
principal = require_user(auth.MANAGER)
policy = get_policy()

artifact = get_model()
max_rows = policy.batch.max_rows

st.warning(f"**{PROTOTYPE_NOTICE}.** Results support pre-screening only.")
st.caption(thresholds_note(policy))
st.caption(
    "Each scored row is recorded in the decision audit trail: its model input fields, the "
    "result and the versions used, under your account's random reference. Names and your "
    "applicant IDs are not stored there. An anonymised summary of the batch (counts, "
    "approval rate, top rejection reasons) is also saved for Analytics."
    if not policy.storage.store_applicant_ids
    else "Storage of applicant IDs is ENABLED in config/policies/personal.yaml: per-row IDs "
    "and statuses are saved with the batch summary."
)

# ---- Template and upload -------------------------------------------------------------------
st.subheader("1. Prepare your file")
st.markdown(
    f"Upload a CSV with one applicant per row, **up to {max_rows:,} rows**. Required columns: "
    + ", ".join(f"`{c}`" for c in batch.REQUIRED_COLUMNS)
    + f". An optional `{batch.ID_COLUMN}` column is copied to the results. An optional "
    f"`{batch.PRODUCT_COLUMN}` column sets each row's loan type ("
    + ", ".join(list_profiles())
    + f"; blank means {DEFAULT_PROFILE}); any other value is reported as a row problem. "
    "Loan types change the rules and assumptions, not the model. Headers are matched "
    "ignoring case and spaces, and common names such as *Income* or *annual_income* are "
    "recognised. Amounts may be written like 12,50,000."
)
st.download_button(
    "Download CSV template",
    data=batch.template_csv(),
    file_name="loanlens_template.csv",
    mime="text/csv",
)

st.subheader("2. Upload and check")
uploaded = st.file_uploader("CSV file", type=["csv", "txt"])
include_positive = st.checkbox(
    "Also list positive factors for approved applicants (slower)", value=False
)

if uploaded is None:
    footer()
    st.stop()

data = uploaded.getvalue()
key = hashlib.sha256(data).hexdigest() + f"|{include_positive}"

if st.session_state.get("batch_key") != key:
    try:
        parsed = batch.parse_upload(data, policy)
    except batch.BatchError as exc:
        st.error(str(exc))
        footer()
        st.stop()
    except Exception:  # noqa: BLE001 - never show a stack trace
        friendly_failure("reading the file")
        footer()
        st.stop()

    progress = st.progress(0.0, text="Scoring applicants...")
    try:
        run = services.score_batch_upload(
            principal,
            parsed,
            policy,
            artifact=artifact,
            include_positive=include_positive,
            progress=lambda f: progress.progress(f, text=f"Scoring applicants... {f:.0%}"),
        )
        results = run.results
    except auth.AuthorisationError as exc:
        progress.empty()
        st.error(f"{exc} Open Sign in in the sidebar.")
        footer()
        st.stop()
    except DatabaseError:
        progress.empty()
        st.error(
            "The results could not be recorded in the decision audit trail, so they are not "
            "shown. Ask the administrator to check the database, then upload the file again."
        )
        footer()
        st.stop()
    except Exception:  # noqa: BLE001
        progress.empty()
        friendly_failure("scoring the file")
        footer()
        st.stop()
    progress.empty()
    summary = batch.summarise(results, parsed)
    try:
        services.save_batch_summary(
            principal, summary, str(artifact.get("version", "unknown")), results, policy
        )
        saved, save_note = True, ""
    except DatabaseError as exc:  # plain message, never a stack trace
        saved, save_note = False, str(exc)
    except Exception:  # noqa: BLE001 - storage problems must not block the results
        saved, save_note = False, "The anonymised summary could not be saved this time."
    st.session_state.update(
        batch_key=key, batch_parsed=parsed, batch_results=results, batch_summary=summary,
        batch_saved=saved, batch_save_note=save_note,
    )  # fmt: skip

parsed = st.session_state["batch_parsed"]
results: pd.DataFrame = st.session_state["batch_results"]
summary = st.session_state["batch_summary"]

if parsed.renamed:
    st.caption(
        "Columns recognised: " + ", ".join(f"'{k}' as `{v}`" for k, v in parsed.renamed.items())
    )
if parsed.ignored:
    st.caption("Columns not used: " + ", ".join(f"'{c}'" for c in parsed.ignored))
if parsed.errors:
    with st.container(key="panel_warning_skipped"):
        st.warning(
            f"{len(parsed.errors):,} of {parsed.total_rows:,} rows have problems and were "
            "skipped. The rest were scored."
        )
        with st.expander(f"Show the {len(parsed.errors):,} skipped rows"):
            st.dataframe(
                batch.errors_frame(parsed.errors), hide_index=True, use_container_width=True
            )
else:
    st.success(f"All {parsed.total_rows:,} rows passed validation.")
if not st.session_state.get("batch_saved", True):
    note = st.session_state.get("batch_save_note") or "The summary could not be saved."
    st.caption(f"Note: {note}")

if results.empty:
    st.error("No valid rows to score. Please fix the problems listed above and upload again.")
    footer()
    st.stop()

# ---- Summary -------------------------------------------------------------------------------
st.subheader("3. Summary")
cards = [
    ("primary", "Total scored", f"{summary['valid_rows']:,}"),
    ("approved", "Approved", f"{summary['approved']:,}"),
    ("rejected", "Rejected", f"{summary['rejected']:,}"),
    ("warning", "Borderline", f"{summary['borderline']:,}"),
    ("neutral", "Skipped rows", f"{summary['invalid_rows']:,}"),
    ("primary", "Approval rate", f"{summary['approval_rate']:.0%}"),
]
for i, (col, (tone, label, value)) in enumerate(zip(st.columns(len(cards)), cards, strict=True)):
    with col, st.container(key=f"kpi_{tone}_{i}"):
        st.metric(label, value)
if summary["top_rejection_reasons"]:
    st.markdown("**Top rejection reasons**")
    st.dataframe(
        pd.DataFrame(summary["top_rejection_reasons"])[["reason", "count"]],
        hide_index=True,
        use_container_width=True,
    )

# ---- Results -------------------------------------------------------------------------------
st.subheader("4. Results")
f1, f2, f3 = st.columns([1, 1, 2])
statuses = f1.multiselect("Status", ["Approved", "Rejected"], default=[])
border_choice = f2.selectbox("Borderline", ["All", "Borderline only", "Not borderline"])
search = f3.text_input("Search ID or reasons")
border = {"All": None, "Borderline only": True, "Not borderline": False}[border_choice]
view = batch.filter_results(results, statuses, border, search)
st.caption(f"Showing {len(view):,} of {len(results):,} scored applicants. {SCORE_LABEL}.")
if len(view) > STYLED_ROWS_LIMIT:
    st.caption(
        f"Status colours are shown for up to {STYLED_ROWS_LIMIT:,} rows; filter to see them. "
        "The Approved / Rejected labels are always shown."
    )
shown = status_display_frame(view.drop(columns=["reason_codes"]))
st.dataframe(
    style_status_column(shown) if len(shown) <= STYLED_ROWS_LIMIT else shown,
    hide_index=True,
    use_container_width=True,
    column_config={
        "probability": st.column_config.NumberColumn("probability", format="%.4f"),
        "borderline": st.column_config.CheckboxColumn("borderline"),
    },
)
st.download_button(
    "Download all results (CSV)",
    data=batch.results_csv(results),
    file_name="loanlens_results.csv",
    mime="text/csv",
    type="primary",
)
footer()
