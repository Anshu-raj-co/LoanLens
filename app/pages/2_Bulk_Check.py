"""Bulk Check (bank managers only): upload a file as a background job, follow it, download."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
from ui_common import footer, friendly_failure, get_policy, require_user, setup_page

from loanlens import auth, batch, hosted, jobs, services, worker
from loanlens.auth.settings import ConfigurationError
from loanlens.config import DEFAULT_PROFILE, list_profiles
from loanlens.db.engine import DatabaseError
from loanlens.formatting import SCORE_LABEL
from loanlens.presentation import PROTOTYPE_NOTICE, thresholds_note
from loanlens.theme import status_display_frame, style_status_column

ACTIVE_KEY = "bulk_active_job"
SELECTED_KEY = "bulk_selected_job"
PREPARED_KEY = "bulk_prepared_job"
POLL_SECONDS = 2
PREVIEW_ROWS = 1_000
DIRECT_DOWNLOAD_MB = 25  # larger files are read only after "Prepare downloads"
UI_DOWNLOAD_MAX_MB = 200  # larger files: use the API
STATUS_TEXT = {
    jobs.QUEUED: "Queued", jobs.RUNNING: "Running", jobs.COMPLETED: "Completed",
    jobs.FAILED: "Failed", jobs.CANCELLED: "Cancelled", jobs.EXPIRED: "Expired",
}  # fmt: skip

setup_page("Bulk Check")
principal = require_user(auth.MANAGER)
policy = get_policy()

try:
    settings = jobs.load_job_settings()
except ConfigurationError as exc:
    st.error(str(exc))
    footer()
    st.stop()


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S UTC") if value else ""


def _stop_with(message: str) -> None:
    st.error(message)
    footer()
    st.stop()


st.warning(f"**{PROTOTYPE_NOTICE}.** Results support pre-screening only.")
if hosted.is_hosted():
    st.warning(
        "This is a hosted demonstration. Upload only synthetic or test data, never real "
        f"applicant data. Here one job accepts at most {settings.max_rows:,} rows and "
        f"{settings.max_upload_mb} MB, job files are kept in temporary storage and are lost "
        "when the host restarts, and a restart interrupts a running job (it is marked failed "
        "within about five minutes and can be submitted again)."
    )
st.caption(thresholds_note(policy))
st.caption(
    "Each scored row is recorded in the decision audit trail: its model input fields, the "
    "result and the versions used, under your account's random reference. Names and your "
    "applicant IDs are not stored there. An anonymised summary of each batch is saved for "
    f"Analytics. The uploaded file is deleted when the job ends; the results and errors files "
    f"(which contain your applicant IDs) are deleted after {settings.retention_days} days. "
    "Every manager can see every manager's jobs."
)

try:
    worker_mode = worker.ensure_worker(settings=settings)
except DatabaseError as exc:
    _stop_with(str(exc))
except Exception:  # noqa: BLE001 - never a stack trace
    friendly_failure("starting the batch worker")
    footer()
    st.stop()

# ---- Template and upload -------------------------------------------------------------------
st.subheader("1. Prepare your file")
max_mb = min(int(st.get_option("server.maxUploadSize")), settings.max_upload_mb)
st.markdown(
    f"Upload a CSV or Parquet file with one applicant per row, **up to {settings.max_rows:,} "
    f"rows and {max_mb} MB**. Required columns: "
    + ", ".join(f"`{c}`" for c in batch.REQUIRED_COLUMNS)
    + f". An optional `{batch.ID_COLUMN}` column is copied to the results. An optional "
    f"`{batch.PRODUCT_COLUMN}` column sets each row's loan type ("
    + ", ".join(list_profiles())
    + "; blank means the loan type chosen below); any other value is reported as a row "
    "problem. Loan types change the rules and assumptions, not the model. Headers are "
    "matched ignoring case and spaces, and common names such as *Income* or *annual_income* "
    "are recognised. Amounts may be written like 12,50,000."
)
st.download_button(
    "Download CSV template",
    data=batch.template_csv(),
    file_name="loanlens_template.csv",
    mime="text/csv",
)

st.subheader("2. Upload and submit")
with st.form("bulk_submit", clear_on_submit=True):
    uploaded = st.file_uploader("CSV or Parquet file", type=["csv", "txt", "parquet"])
    profiles = list_profiles()
    product = st.selectbox(
        "Loan type", profiles, index=profiles.index(DEFAULT_PROFILE), key="bulk_product"
    )
    include_positive = st.checkbox(
        "Also list positive factors for approved applicants (slower)", value=False
    )
    submitted = st.form_submit_button("Submit job", type="primary")

if submitted:
    if uploaded is None:
        st.error("Choose a CSV or Parquet file first.")
    else:
        try:
            job = services.submit_batch_job(
                principal, uploaded, getattr(uploaded, "name", "upload"),
                product=product, include_positive=include_positive,
            )  # fmt: skip
            st.session_state[ACTIVE_KEY] = job.id
            st.session_state[SELECTED_KEY] = job.id
        except auth.AuthorisationError as exc:
            _stop_with(f"{exc} Open Sign in in the sidebar.")
        except batch.BatchError as exc:
            st.error(str(exc))
        except DatabaseError as exc:
            st.error(str(exc))
        except Exception:  # noqa: BLE001
            friendly_failure("saving the file")

if worker_mode == jobs.EXTERNAL:
    st.caption("Jobs are processed by an external worker (python -m loanlens.worker).")
elif worker_mode == jobs.EMBEDDED:
    st.caption(
        "Jobs are processed by a background worker inside this app. A restart of the app "
        "interrupts a running job; it is then marked failed and can be submitted again."
    )
else:
    st.warning(
        "No batch worker is running, so submitted jobs wait in the queue. Start one with "
        "`python -m loanlens.worker`, or set LOANLENS_EMBEDDED_WORKER=1."
    )


# ---- Progress of the active job (polled without a busy loop) -------------------------------
@st.fragment(run_every=POLL_SECONDS)
def progress_panel(job_id: str) -> None:
    """Show the active job's progress; reruns every few seconds until it has finished."""
    try:
        job = services.get_batch_job(principal, job_id)
    except jobs.JobNotFound:
        st.session_state.pop(ACTIVE_KEY, None)
        return
    except Exception:  # noqa: BLE001
        st.caption("Progress could not be read just now; trying again.")
        return
    if job.finished:
        st.session_state.pop(ACTIVE_KEY, None)
        st.session_state[SELECTED_KEY] = job.id
        st.rerun()
    total = f"{job.rows_total:,}" if job.rows_total else "counting"
    text = (
        f"{STATUS_TEXT[job.status]}: {job.filename} - {job.rows_processed:,} of about {total} "
        f"rows ({job.approved:,} Approved, {job.rejected:,} Rejected, "
        f"{job.rows_skipped:,} skipped)"
    )
    st.progress(job.fraction, text=text)
    if job.cancel_requested:
        st.caption("Cancelling after the current chunk...")
    elif st.button("Cancel this job", key=f"cancel_{job.id}"):
        services.cancel_batch_job(principal, job.id)
        st.rerun()


active = st.session_state.get(ACTIVE_KEY)
if active:
    st.subheader("3. Progress")
    progress_panel(active)

# ---- Jobs ----------------------------------------------------------------------------------
st.subheader("Batch jobs")
try:
    job_list = services.list_batch_jobs(principal, 50)
except DatabaseError as exc:
    _stop_with(str(exc))
if not job_list:
    st.info("No batch job yet. Upload a file above.")
    footer()
    st.stop()

table = pd.DataFrame(
    [
        {
            "Submitted": _when(j.created_at),
            "File": j.filename,
            "Loan type": j.profile,
            "Status": STATUS_TEXT[j.status],
            "Rows": j.rows_processed,
            "Approved": j.approved,
            "Rejected": j.rejected,
            "Borderline": j.borderline,
            "Skipped": j.rows_skipped,
            "Finished": _when(j.finished_at),
            "Note": j.error_message or "",
        }  # fmt: skip
        for j in job_list
    ]
)
st.dataframe(table, hide_index=True, use_container_width=True)

ids = [j.id for j in job_list]
by_id = {j.id: j for j in job_list}
selected = st.session_state.get(SELECTED_KEY)
choice = st.selectbox(
    "Show a job",
    ids,
    index=ids.index(selected) if selected in ids else 0,
    format_func=lambda i: (
        f"{_when(by_id[i].created_at)} - {by_id[i].filename} - {STATUS_TEXT[by_id[i].status]}"
    ),
)
job = by_id[choice]

if job.status in (jobs.QUEUED, jobs.RUNNING):
    st.info(f"This job is {STATUS_TEXT[job.status].lower()}. Its results appear here when it "
            "has completed.")  # fmt: skip
    if job.id != st.session_state.get(ACTIVE_KEY) and st.button("Follow its progress"):
        st.session_state[ACTIVE_KEY] = job.id
        st.rerun()
    footer()
    st.stop()
if job.status != jobs.COMPLETED:
    st.error(f"This job {STATUS_TEXT[job.status].lower()}. {job.error_message or ''}".strip())
    footer()
    st.stop()

# ---- Summary of the selected job -----------------------------------------------------------
st.subheader("Summary")
if job.rows_skipped:
    with st.container(key="panel_warning_skipped"):
        st.warning(
            f"{job.rows_skipped:,} of {job.rows_processed:,} rows have problems and were "
            "skipped. The rest were scored. Download the errors file for the row numbers."
        )
else:
    st.success(f"All {job.rows_processed:,} rows passed validation.")
if job.error_message:
    st.caption(f"Note: {job.error_message}")
scored = job.approved + job.rejected
cards = [
    ("primary", "Total scored", f"{scored:,}"),
    ("approved", "Approved", f"{job.approved:,}"),
    ("rejected", "Rejected", f"{job.rejected:,}"),
    ("warning", "Borderline", f"{job.borderline:,}"),
    ("neutral", "Skipped rows", f"{job.rows_skipped:,}"),
    ("primary", "Approval rate", f"{job.approved / scored:.0%}" if scored else "-"),
]
for i, (col, (tone, label, value)) in enumerate(zip(st.columns(len(cards)), cards, strict=True)):
    with col, st.container(key=f"kpi_{tone}_{i}"):
        st.metric(label, value)
reasons = (job.summary or {}).get("top_rejection_reasons") or []
if reasons:
    st.markdown("**Top rejection reasons**")
    st.dataframe(
        pd.DataFrame(reasons)[["reason", "count"]], hide_index=True, use_container_width=True
    )

# ---- Downloads and preview -----------------------------------------------------------------
st.subheader("Downloads")
try:
    files = {
        kind: services.batch_job_file(principal, job.id, kind)
        for kind in ("result_csv", "result", "errors")
    }
except jobs.JobFileUnavailable as exc:
    _stop_with(str(exc))
sizes = {k: p.stat().st_size / 1024 / 1024 for k, p in files.items()}
labels = {
    "result_csv": ("Download results (CSV)", "text/csv", "csv", "loanlens_results"),
    "result": (
        "Download results (Parquet)",
        "application/octet-stream",
        "parquet",
        "loanlens_results",
    ),  # fmt: skip
    "errors": ("Download skipped rows (CSV)", "text/csv", "csv", "loanlens_errors"),
}
needs_prepare = any(size > DIRECT_DOWNLOAD_MB for size in sizes.values())
ready = not needs_prepare or st.session_state.get(PREPARED_KEY) == job.id
if not ready:
    st.caption(
        f"The files are large ({sum(sizes.values()):,.0f} MB in total), so they are read only "
        "when you ask."
    )
    if st.button("Prepare downloads"):
        st.session_state[PREPARED_KEY] = job.id
        st.rerun()
else:
    columns = st.columns(3)
    for col, kind in zip(columns, labels, strict=True):
        label, mime, ext, stem = labels[kind]
        if sizes[kind] > UI_DOWNLOAD_MAX_MB:
            col.caption(f"{label[9:]}: {sizes[kind]:,.0f} MB; download it through the API "
                        f"(GET /v1/batches/{job.id}/...).")  # fmt: skip
            continue
        col.download_button(
            label, data=files[kind].read_bytes(), file_name=f"{stem}_{job.id[:8]}.{ext}",
            mime=mime, type="primary" if kind == "result_csv" else "secondary",
            key=f"dl_{kind}_{job.id}",
        )  # fmt: skip

st.subheader("Preview")
try:
    preview = services.batch_job_preview(principal, job.id, "result", PREVIEW_ROWS)
except Exception:  # noqa: BLE001
    friendly_failure("reading the results")
    footer()
    st.stop()
st.caption(
    f"The first {min(len(preview), PREVIEW_ROWS):,} of {scored:,} scored applicants. "
    f"Download the file for all of them. {SCORE_LABEL}."
)
shown = status_display_frame(preview.drop(columns=["reason_codes"], errors="ignore"))
st.dataframe(
    style_status_column(shown),
    hide_index=True,
    use_container_width=True,
    column_config={
        "probability": st.column_config.NumberColumn("probability", format="%.4f"),
        "borderline": st.column_config.CheckboxColumn("borderline"),
    },
)
if job.rows_skipped:
    with st.expander(f"Show the first skipped rows (of {job.rows_skipped:,})"):
        st.dataframe(
            services.batch_job_preview(principal, job.id, "errors", PREVIEW_ROWS),
            hide_index=True,
            use_container_width=True,
        )
footer()
