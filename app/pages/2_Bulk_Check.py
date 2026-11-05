"""Bank manager mode: upload a CSV, validate, score every applicant, download results."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st
from ui_common import footer, friendly_failure, get_model, get_policy, setup_page

from loanlens import batch, storage
from loanlens.formatting import SCORE_LABEL
from loanlens.presentation import PROTOTYPE_NOTICE, thresholds_note

setup_page("Bulk Check", "🏦")
policy = get_policy()

with st.sidebar:
    manager_mode = st.toggle(
        "Bank manager mode",
        key="manager_mode",
        help="Prototype gate only. Real authentication is future work.",
    )

if not manager_mode:
    st.info(
        "Bulk Check is for bank staff. Turn on **Bank manager mode** in the sidebar to "
        "continue. (Prototype: this is a simple switch, not real authentication.)"
    )
    footer()
    st.stop()

artifact = get_model()
max_rows = policy.batch.max_rows

st.warning(f"**{PROTOTYPE_NOTICE}.** Results support pre-screening only.")
st.caption(thresholds_note(policy))
st.caption(
    "Only an anonymised summary of each batch (counts, approval rate, top rejection reasons) "
    "is saved. Names, IDs and applicant details are not stored."
    if not policy.storage.store_applicant_ids
    else "Storage of applicant IDs is ENABLED in config/policy.yaml: per-row IDs and "
    "statuses are saved with the batch summary."
)

# ---- Template and upload -------------------------------------------------------------------
st.subheader("1. Prepare your file")
st.markdown(
    f"Upload a CSV with one applicant per row, **up to {max_rows:,} rows**. Required columns: "
    + ", ".join(f"`{c}`" for c in batch.REQUIRED_COLUMNS)
    + f". An optional `{batch.ID_COLUMN}` column is copied to the results. Headers are matched "
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
        results = batch.score(
            parsed,
            policy,
            artifact,
            include_positive=include_positive,
            progress=lambda f: progress.progress(f, text=f"Scoring applicants... {f:.0%}"),
        )
    except Exception:  # noqa: BLE001
        progress.empty()
        friendly_failure("scoring the file")
        footer()
        st.stop()
    progress.empty()
    summary = batch.summarise(results, parsed)
    try:
        storage.save_summary(summary, str(artifact.get("version", "unknown")), results, policy)
        saved = True
    except Exception:  # noqa: BLE001 - storage problems must not block the results
        saved = False
    st.session_state.update(
        batch_key=key, batch_parsed=parsed, batch_results=results, batch_summary=summary,
        batch_saved=saved,
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
    st.warning(
        f"{len(parsed.errors):,} of {parsed.total_rows:,} rows have problems and were skipped. "
        "The rest were scored."
    )
    with st.expander(f"Show the {len(parsed.errors):,} skipped rows"):
        st.dataframe(batch.errors_frame(parsed.errors), hide_index=True, use_container_width=True)
else:
    st.success(f"All {parsed.total_rows:,} rows passed validation.")
if not st.session_state.get("batch_saved", True):
    st.caption("Note: the anonymised summary could not be saved this time.")

if results.empty:
    st.error("No valid rows to score. Please fix the problems listed above and upload again.")
    footer()
    st.stop()

# ---- Summary -------------------------------------------------------------------------------
st.subheader("3. Summary")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Scored", f"{summary['valid_rows']:,}")
c2.metric("Approved", f"{summary['approved']:,}")
c3.metric("Rejected", f"{summary['rejected']:,}")
c4.metric("Borderline", f"{summary['borderline']:,}")
c5.metric("Approval rate", f"{summary['approval_rate']:.0%}")
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
st.dataframe(
    view.drop(columns=["reason_codes"]),
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
