"""Background batch jobs: settings, private files and the ``batch_jobs`` table (internal).

Pages and the API do not call this module directly; they go through
:mod:`loanlens.services`, which checks the signed-in manager first. The worker
(:mod:`loanlens.worker`) claims and runs jobs without any session token: the submitting
manager's ``audit_ref`` is stored on the job at submission.

Files: uploads and results are kept in a private directory (``LOANLENS_JOBS_DIR``, default
``data/jobs/``, gitignored) under random names. The database stores only those names, and
:func:`job_file` accepts nothing else, so no path from a client is ever opened or served.
Result and error files can contain applicant IDs from the upload, so they are deleted after
``LOANLENS_JOB_RETENTION_DAYS`` (default 7) by ``python -m loanlens.worker --cleanup``
(workers also run the clean-up when they start).

Settings (environment variables, names in ``.env.example``):

* ``LOANLENS_JOBS_DIR``: private directory for uploads and results.
* ``LOANLENS_JOB_RETENTION_DAYS``: days before finished jobs' files are deleted (default 7).
* ``LOANLENS_EMBEDDED_WORKER``: start a background-thread worker inside the app when no
  external worker is running (default on).
* ``LOANLENS_JOB_CHUNK_SIZE``: rows read and scored per step (default 20,000).
* ``LOANLENS_JOB_MAX_ROWS``: most rows in one job (default 1,000,000).
* ``LOANLENS_JOB_MAX_UPLOAD_MB``: largest upload through the API (default 200; the
  Streamlit limit is ``server.maxUploadSize`` in ``.streamlit/config.toml``).
* ``LOANLENS_BATCH_AUDIT``: ``row`` (default) writes one audit record per scored row;
  ``off`` writes none and is meant for benchmarks only. It is refused when
  ``LOANLENS_ENV=production`` or ``LOANLENS_HOSTED=1``.
* ``LOANLENS_BATCH_AUDIT_CHUNK``: audit records per bulk insert (default 1,000).
* ``LOANLENS_WORKER_POLL_SECONDS`` (default 2) and ``LOANLENS_JOB_STALE_SECONDS`` (default
  300): how often an idle worker looks for jobs, and how long a running job may go without
  a heartbeat before it is marked failed.

With ``LOANLENS_HOSTED=1`` the defaults are smaller (chunks of 5,000 rows, at most 200,000
rows and 50 MB per job, files in a temporary directory); see :mod:`loanlens.hosted`.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import unicodedata
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import and_, delete, or_, select, update

from loanlens import hosted
from loanlens.auth.settings import ConfigurationError, is_production
from loanlens.batch import CSV_FORMAT, PARQUET_FORMAT, PARQUET_MAGIC, BatchError
from loanlens.config import PROJECT_ROOT
from loanlens.db.engine import get_engine, is_sqlite, session_scope
from loanlens.db.models import BatchJob, BatchWorker, User

QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED, EXPIRED = (
    "queued", "running", "completed", "failed", "cancelled", "expired",
)  # fmt: skip
FINISHED = (COMPLETED, FAILED, CANCELLED, EXPIRED)
EXTERNAL, EMBEDDED = "external", "embedded"

ENV_JOBS_DIR = "LOANLENS_JOBS_DIR"
ENV_RETENTION = "LOANLENS_JOB_RETENTION_DAYS"
ENV_EMBEDDED = "LOANLENS_EMBEDDED_WORKER"
ENV_CHUNK = "LOANLENS_JOB_CHUNK_SIZE"
ENV_MAX_ROWS = "LOANLENS_JOB_MAX_ROWS"
ENV_MAX_UPLOAD_MB = "LOANLENS_JOB_MAX_UPLOAD_MB"
ENV_AUDIT = "LOANLENS_BATCH_AUDIT"
ENV_AUDIT_CHUNK = "LOANLENS_BATCH_AUDIT_CHUNK"
ENV_POLL = "LOANLENS_WORKER_POLL_SECONDS"
ENV_STALE = "LOANLENS_JOB_STALE_SECONDS"
DEFAULT_JOBS_DIR = PROJECT_ROOT / "data" / "jobs"

_ENV = {
    "retention_days": ENV_RETENTION,
    "chunk_size": ENV_CHUNK,
    "max_rows": ENV_MAX_ROWS,
    "max_upload_mb": ENV_MAX_UPLOAD_MB,
    "audit": ENV_AUDIT,
    "audit_chunk_size": ENV_AUDIT_CHUNK,
    "poll_seconds": ENV_POLL,
    "stale_seconds": ENV_STALE,
}
_FALSE = {"0", "false", "no", "off"}
_FILE_NAME = re.compile(r"^[0-9a-f]{32}\.(csv|parquet)$")
JOB_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_JOB_ID = re.compile(JOB_ID_PATTERN)
_COPY_BLOCK = 1 << 20


class JobNotFound(LookupError):
    """No job with that id."""

    def __init__(self) -> None:
        super().__init__("No batch job with that id was found.")


class JobFileUnavailable(RuntimeError):
    """The requested file does not exist (yet, or any more); the message says why."""


class UploadTooLarge(BatchError):
    """The upload is larger than the configured limit."""


class JobSettings(BaseModel):
    """Validated job settings."""

    model_config = ConfigDict(frozen=True)

    jobs_dir: Path = DEFAULT_JOBS_DIR
    retention_days: int = Field(7, ge=1, le=3650)
    embedded_worker: bool = True
    chunk_size: int = Field(20_000, ge=100, le=500_000)
    max_rows: int = Field(1_000_000, ge=1, le=10_000_000)
    max_upload_mb: int = Field(200, ge=1, le=4096)
    audit: Literal["row", "off"] = "row"
    audit_chunk_size: int = Field(1_000, ge=1, le=100_000)
    poll_seconds: float = Field(2.0, ge=0.05, le=60)
    stale_seconds: int = Field(300, ge=5, le=86_400)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_job_settings(environ: Mapping[str, str] | None = None) -> JobSettings:
    """Settings from the environment; an invalid value raises :class:`ConfigurationError`."""
    environ = os.environ if environ is None else environ
    values: dict[str, Any] = {
        k: environ[v].strip() for k, v in _ENV.items() if environ.get(v, "").strip()
    }
    if hosted.is_hosted(environ):  # smaller defaults for a ~1 GB host (see loanlens.hosted)
        values.setdefault("chunk_size", hosted.HOSTED_CHUNK_SIZE)
        values.setdefault("max_rows", hosted.HOSTED_MAX_ROWS)
        values.setdefault("max_upload_mb", hosted.HOSTED_MAX_UPLOAD_MB)
        values["jobs_dir"] = hosted.HOSTED_JOBS_DIR
    if environ.get(ENV_JOBS_DIR, "").strip():
        path = Path(environ[ENV_JOBS_DIR].strip())
        values["jobs_dir"] = path if path.is_absolute() else PROJECT_ROOT / path
    if environ.get(ENV_EMBEDDED, "").strip():
        values["embedded_worker"] = environ[ENV_EMBEDDED].strip().lower() not in _FALSE
    try:
        settings = JobSettings(**values)
    except ValidationError as exc:
        names = ", ".join(_ENV.get(str(e["loc"][0]), str(e["loc"][0])) for e in exc.errors())
        raise ConfigurationError(
            f"Invalid setting: {names}. Use a value within the documented range."
        ) from None
    if settings.audit == "off" and is_production(environ):
        raise ConfigurationError(
            f"{ENV_AUDIT}=off is for benchmarks only and is refused in production or hosted mode."
        )
    return settings


# ---- Files -----------------------------------------------------------------------------------


def jobs_dir(settings: JobSettings) -> Path:
    """The private jobs directory (created if needed)."""
    path = Path(settings.jobs_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_file_name(fmt: str) -> str:
    """A random file name with the format's extension (never the client's name)."""
    if fmt not in (CSV_FORMAT, PARQUET_FORMAT):
        raise ValueError("Unknown file format.")
    return f"{secrets.token_hex(16)}.{fmt}"


def job_file(settings: JobSettings, name: str | None) -> Path:
    """The path of a stored job file. Only names made by :func:`new_file_name` are accepted.

    Raises:
        JobFileUnavailable: the name is missing or not a valid stored file name.
    """
    if not name or not _FILE_NAME.fullmatch(name):
        raise JobFileUnavailable("This file is not available.")
    base = jobs_dir(settings)
    path = (base / name).resolve()
    if path.parent != base:  # defence in depth; the pattern already forbids separators
        raise JobFileUnavailable("This file is not available.")
    return path


def remove_file(settings: JobSettings, name: str | None) -> None:
    """Delete a stored job file if it exists (invalid names are ignored)."""
    try:
        job_file(settings, name).unlink(missing_ok=True)
    except (JobFileUnavailable, OSError):
        pass


def display_name(filename: str | None) -> str:
    """The client's file name for display only: base name, no control characters, 120 max."""
    text = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C").strip()
    return (text or "upload")[:120]


def save_upload(settings: JobSettings, stream: BinaryIO) -> tuple[str, str]:
    """Copy an upload into the jobs directory in blocks; returns (stored name, format).

    The format is detected from the content (Parquet magic bytes), not the client's name.

    Raises:
        UploadTooLarge: more than ``max_upload_mb``.
        BatchError: the upload is empty.
    """
    base = jobs_dir(settings)
    tmp = base / f"{secrets.token_hex(16)}.part"
    size = 0
    try:
        with open(tmp, "wb") as out:
            while block := stream.read(_COPY_BLOCK):
                size += len(block)
                if size > settings.max_upload_bytes:
                    raise UploadTooLarge(
                        f"The file is larger than {settings.max_upload_mb} MB, the most one "
                        "upload accepts. Please split it into smaller files."
                    )
                out.write(block)
        if size == 0:
            raise BatchError("The file is empty. Please upload a CSV with a header row and data.")
        with open(tmp, "rb") as fh:
            fmt = PARQUET_FORMAT if fh.read(4) == PARQUET_MAGIC else CSV_FORMAT
        name = new_file_name(fmt)
        shutil.move(tmp, base / name)
        return name, fmt
    finally:
        tmp.unlink(missing_ok=True)


# ---- Rows ------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class JobView:
    """A job as pages and the API see it (no worker internals, no file locations)."""

    id: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    filename: str
    profile: str
    include_positive: bool
    input_format: str
    rows_total: int | None
    rows_processed: int
    rows_skipped: int
    rows_audited: int
    approved: int
    rejected: int
    borderline: int
    error_message: str | None
    audit_batch_id: str | None
    audited: bool
    cancel_requested: bool
    summary: dict[str, Any] | None
    has_result: bool
    has_errors: bool

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

    @property
    def fraction(self) -> float:
        """Progress from 0 to 1 (1 when completed)."""
        if self.status == COMPLETED:
            return 1.0
        if not self.rows_total:
            return 0.0
        return max(0.0, min(1.0, self.rows_processed / self.rows_total))


def view(job: BatchJob) -> JobView:
    """A :class:`JobView` of a row."""
    return JobView(
        id=job.id, created_by=job.created_by, created_at=_aware(job.created_at),
        started_at=_aware(job.started_at), finished_at=_aware(job.finished_at),
        status=job.status, filename=job.filename, profile=job.profile,
        include_positive=bool(job.include_positive), input_format=job.input_format,
        rows_total=job.rows_total, rows_processed=job.rows_processed or 0,
        rows_skipped=job.rows_skipped or 0, rows_audited=job.rows_audited or 0,
        approved=job.approved or 0, rejected=job.rejected or 0, borderline=job.borderline or 0,
        error_message=job.error_message, audit_batch_id=job.audit_batch_id,
        audited=bool(job.audited), cancel_requested=bool(job.cancel_requested),
        summary=json.loads(job.summary) if job.summary else None,
        has_result=bool(job.result_path), has_errors=bool(job.errors_path),
    )  # fmt: skip


def valid_job_id(job_id: str) -> bool:
    """True for a well-formed job id (a lower-case UUID)."""
    return bool(_JOB_ID.fullmatch(str(job_id or "")))


def create_job(
    url: str,
    *,
    created_by: str,
    filename: str,
    profile: str,
    include_positive: bool,
    input_format: str,
    upload_path: str,
) -> JobView:
    """Insert a queued job."""
    job = BatchJob(
        id=str(uuid.uuid4()), created_by=created_by, created_at=_now(), status=QUEUED,
        filename=display_name(filename), profile=profile, include_positive=include_positive,
        input_format=input_format, upload_path=upload_path, rows_processed=0, rows_skipped=0,
        rows_audited=0, approved=0, rejected=0, borderline=0, audited=True,
        cancel_requested=False,
    )  # fmt: skip
    with session_scope(url) as session:
        session.add(job)
        session.flush()
        return view(job)


def get_row(url: str, job_id: str) -> BatchJob | None:
    """The full row (internal: includes file names), or None."""
    if not valid_job_id(job_id):
        return None
    with session_scope(url) as session:
        job = session.get(BatchJob, job_id)
        if job is not None:
            session.expunge(job)
        return job


def get_job(url: str, job_id: str) -> JobView:
    """One job.

    Raises:
        JobNotFound: no such job.
    """
    job = get_row(url, job_id)
    if job is None:
        raise JobNotFound()
    return view(job)


def list_jobs(url: str, limit: int = 50) -> list[JobView]:
    """Most recent jobs first."""
    with session_scope(url) as session:
        rows = session.execute(
            select(BatchJob).order_by(BatchJob.created_at.desc(), BatchJob.id).limit(int(limit))
        ).scalars().all()  # fmt: skip
        return [view(r) for r in rows]


def claim_next(url: str, worker_id: str) -> BatchJob | None:
    """Atomically claim the oldest queued job for ``worker_id`` (None when there is none).

    PostgreSQL: ``SELECT ... FOR UPDATE SKIP LOCKED`` inside one transaction, so concurrent
    workers skip a row another worker is claiming. SQLite: one conditional ``UPDATE`` (status
    must still be ``queued``) that marks the row with a fresh claim token; SQLite runs writes
    one at a time, so only one worker's update can match.
    """
    token = str(uuid.uuid4())
    now = _now()
    claim = dict(status=RUNNING, worker_id=worker_id, claim_token=token, started_at=now,
                 heartbeat_at=now)  # fmt: skip
    oldest = (
        select(BatchJob.id).where(BatchJob.status == QUEUED)
        .order_by(BatchJob.created_at, BatchJob.id).limit(1)
    )  # fmt: skip
    with session_scope(url) as session:
        if is_sqlite(url):
            result = session.execute(
                update(BatchJob)
                .where(BatchJob.id == oldest.scalar_subquery(), BatchJob.status == QUEUED)
                .values(**claim)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                return None
        else:
            job_id = session.execute(oldest.with_for_update(skip_locked=True)).scalar()
            if job_id is None:
                return None
            session.execute(
                update(BatchJob).where(BatchJob.id == job_id).values(**claim)
                .execution_options(synchronize_session=False)
            )  # fmt: skip
    with session_scope(url) as session:
        job = session.execute(select(BatchJob).where(BatchJob.claim_token == token)).scalar()
        if job is not None:
            session.expunge(job)
        return job


def _owned(job_id: str, worker_id: str):
    return and_(BatchJob.id == job_id, BatchJob.status == RUNNING, BatchJob.worker_id == worker_id)


def report_progress(url: str, job_id: str, worker_id: str, **counts: Any) -> tuple[bool, bool]:
    """Store counts and a heartbeat; returns (still owned by this worker, cancel requested)."""
    with session_scope(url) as session:
        result = session.execute(
            update(BatchJob).where(_owned(job_id, worker_id))
            .values(heartbeat_at=_now(), **counts)
            .execution_options(synchronize_session=False)
        )  # fmt: skip
        if result.rowcount != 1:
            return False, False
        cancel = session.execute(
            select(BatchJob.cancel_requested).where(BatchJob.id == job_id)
        ).scalar()
        return True, bool(cancel)


def finish(url: str, job_id: str, worker_id: str, status: str, **fields: Any) -> bool:
    """Move a running job owned by ``worker_id`` to a final status; False if not owned."""
    if status not in (COMPLETED, FAILED, CANCELLED):
        raise ValueError("A job can only finish as completed, failed or cancelled.")
    with session_scope(url) as session:
        result = session.execute(
            update(BatchJob).where(_owned(job_id, worker_id))
            .values(status=status, finished_at=_now(), heartbeat_at=_now(), **fields)
            .execution_options(synchronize_session=False)
        )  # fmt: skip
        return result.rowcount == 1


def request_cancel(url: str, job_id: str) -> str:
    """Cancel a queued job now, or ask the worker to stop a running one after its chunk.

    Returns the job's status afterwards (finished jobs are left unchanged).

    Raises:
        JobNotFound: no such job.
    """
    if get_row(url, job_id) is None:
        raise JobNotFound()
    with session_scope(url) as session:
        session.execute(
            update(BatchJob).where(BatchJob.id == job_id, BatchJob.status == QUEUED)
            .values(status=CANCELLED, finished_at=_now(),
                    error_message="Cancelled before it started. No rows were scored.")
            .execution_options(synchronize_session=False)
        )  # fmt: skip
        session.execute(
            update(BatchJob).where(BatchJob.id == job_id, BatchJob.status == RUNNING)
            .values(cancel_requested=True)
            .execution_options(synchronize_session=False)
        )  # fmt: skip
    return get_job(url, job_id).status


def audit_note(rows_audited: int, audit_batch_id: str | None) -> str:
    """Plain note about audit records that remain after a job stopped part-way."""
    if not rows_audited:
        return "No rows were recorded in the audit trail."
    return (
        f"{rows_audited:,} rows were already recorded in the audit trail under batch id "
        f"{audit_batch_id}; those records cannot be removed. Uploading the file again runs it "
        "as a new batch with a new batch id."
    )


def mark_stale(url: str, stale_seconds: int, settings: JobSettings | None = None) -> list[str]:
    """Mark running jobs without a heartbeat for ``stale_seconds`` as failed; returns ids.

    Their partial result files are deleted (when ``settings`` is given) and the upload too.
    """
    cutoff = _now() - timedelta(seconds=stale_seconds)
    with session_scope(url) as session:
        stale = session.execute(
            select(BatchJob).where(
                BatchJob.status == RUNNING,
                or_(BatchJob.heartbeat_at.is_(None), BatchJob.heartbeat_at < cutoff),
            )
        ).scalars().all()  # fmt: skip
        ids = []
        for job in stale:
            message = (
                "The job stopped unexpectedly (the worker or the app was restarted). "
                + audit_note(job.rows_audited or 0, job.audit_batch_id)
            )
            result = session.execute(
                update(BatchJob).where(BatchJob.id == job.id, BatchJob.status == RUNNING,
                                       BatchJob.heartbeat_at == job.heartbeat_at)
                .values(status=FAILED, finished_at=_now(), error_message=message,
                        result_path=None, result_csv_path=None, errors_path=None,
                        upload_path=None)
                .execution_options(synchronize_session=False)
            )  # fmt: skip
            if result.rowcount == 1:
                ids.append(job.id)
                if settings is not None:
                    for name in (job.result_path, job.result_csv_path, job.errors_path,
                                 job.upload_path):  # fmt: skip
                        remove_file(settings, name)
    return ids


def expire_old(url: str, settings: JobSettings, now: datetime | None = None) -> list[str]:
    """Delete the files of jobs finished more than ``retention_days`` ago; mark them expired.

    Also removes uploads of queued jobs older than the retention period (marked expired).
    Returns the ids changed.
    """
    cutoff = (now or _now()) - timedelta(days=settings.retention_days)
    with session_scope(url) as session:
        old = session.execute(
            select(BatchJob).where(
                or_(
                    and_(BatchJob.status.in_((COMPLETED, FAILED, CANCELLED)),
                         BatchJob.finished_at < cutoff),
                    and_(BatchJob.status == QUEUED, BatchJob.created_at < cutoff),
                )
            )
        ).scalars().all()  # fmt: skip
        ids = []
        for job in old:
            for name in (job.result_path, job.result_csv_path, job.errors_path, job.upload_path):
                remove_file(settings, name)
            note = f"Files deleted after {settings.retention_days} days (retention setting)."
            session.execute(
                update(BatchJob).where(BatchJob.id == job.id)
                .values(status=EXPIRED, result_path=None, result_csv_path=None, errors_path=None,
                        upload_path=None, finished_at=job.finished_at or _now(),
                        error_message=((job.error_message + " ") if job.error_message else "")
                        + note)
                .execution_options(synchronize_session=False)
            )  # fmt: skip
            ids.append(job.id)
    return ids


# ---- Workers and owners ---------------------------------------------------------------------


def touch_worker(url: str, worker_id: str, kind: str) -> None:
    """Record that a worker is alive."""
    now = _now()
    with session_scope(url) as session:
        worker = session.get(BatchWorker, worker_id)
        if worker is None:
            session.add(BatchWorker(id=worker_id, kind=kind, started_at=now, last_seen=now))
        else:
            worker.last_seen = now


def remove_worker(url: str, worker_id: str) -> None:
    """Forget a worker that is shutting down."""
    with session_scope(url) as session:
        session.execute(delete(BatchWorker).where(BatchWorker.id == worker_id))


def external_worker_alive(url: str, within_seconds: float) -> bool:
    """True when an external worker reported in during the last ``within_seconds``."""
    cutoff = _now() - timedelta(seconds=within_seconds)
    with session_scope(url) as session:
        found = session.execute(
            select(BatchWorker.id).where(BatchWorker.kind == EXTERNAL,
                                         BatchWorker.last_seen >= cutoff).limit(1)
        ).scalar()  # fmt: skip
        return found is not None


def active_manager(url: str, audit_ref: str) -> bool:
    """True when ``audit_ref`` belongs to an existing, active manager account."""
    with session_scope(url) as session:
        user = session.execute(select(User).where(User.audit_ref == audit_ref)).scalar()
        return bool(user is not None and user.is_active and user.role == "manager")


def dispose(url: str) -> None:
    """Close pooled connections (used by tests that simulate separate processes)."""
    get_engine(url).dispose()
