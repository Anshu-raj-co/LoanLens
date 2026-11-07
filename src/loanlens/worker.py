"""Batch job worker: ``python -m loanlens.worker`` (external) or an embedded thread.

The worker polls ``batch_jobs`` for queued jobs, claims one atomically
(:func:`loanlens.jobs.claim_next`) and streams it through :func:`loanlens.pipeline.run_file`.
It needs no session token: the submitting manager was verified when the job was created,
and the job stores that manager's ``audit_ref``, which the worker uses for the audit records
(``user_ref``; ``actor_role`` "manager"). Before running a job the worker checks that the
reference still belongs to an active manager account; otherwise the job fails.

On start-up a worker marks running jobs without a recent heartbeat as failed and deletes
files past the retention period. While idle it repeats the stale check every minute.

Command line::

    python -m loanlens.worker            # run until stopped (Ctrl+C)
    python -m loanlens.worker --once     # process queued jobs, then exit
    python -m loanlens.worker --cleanup  # delete expired job files, then exit

The app starts an embedded background-thread worker when ``LOANLENS_EMBEDDED_WORKER`` is on
(default) and no external worker has reported in recently. A restart of the app or of a
hosted platform stops the embedded worker; a job it was running is marked failed once its
heartbeat is older than ``LOANLENS_JOB_STALE_SECONDS``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from typing import Any

from loanlens import jobs, pipeline, storage
from loanlens import model as model_mod
from loanlens.audit import new_id
from loanlens.auth.settings import ConfigurationError
from loanlens.batch import BatchError, estimate_rows
from loanlens.config import load_policy, load_profile
from loanlens.db.engine import DatabaseError

logger = logging.getLogger("loanlens.worker")
STALE_CHECK_SECONDS = 60
HEARTBEAT_GRACE = 3  # an external worker counts as running for this many poll intervals


def new_worker_id(kind: str) -> str:
    """A unique worker id (kind, host, process and a random part; no personal data)."""
    host = socket.gethostname()[:20]
    return f"{kind}-{host}-{os.getpid()}-{uuid.uuid4().hex[:8]}"[:64]


def _url() -> str:
    return storage.resolve_url()


def process(
    job: Any,
    *,
    url: str,
    worker_id: str,
    settings: jobs.JobSettings,
    artifact: dict[str, Any] | None = None,
) -> str:
    """Run one claimed job to a final status and return that status.

    Never raises for problems with the file or the database: they end the job as failed
    with a plain message (and the worker carries on).
    """
    upload = job.upload_path
    names = {
        "result_path": jobs.new_file_name("parquet"),
        "result_csv_path": jobs.new_file_name("csv"),
        "errors_path": jobs.new_file_name("csv"),
    }
    audit_on = settings.audit == "row"
    audit_batch_id = new_id() if audit_on else None
    state = {"audited": 0}

    def cleanup_outputs() -> None:
        for name in names.values():
            jobs.remove_file(settings, name)

    def fail(status: str, message: str) -> str:
        cleanup_outputs()
        jobs.finish(
            url, job.id, worker_id, status,
            error_message=f"{message} {jobs.audit_note(state['audited'], audit_batch_id)}".strip(),
            rows_audited=state["audited"], audit_batch_id=audit_batch_id, upload_path=None,
        )  # fmt: skip
        return status

    try:
        if not jobs.active_manager(url, job.created_by):
            return fail(jobs.FAILED, "The manager account that submitted this job is no longer "
                                     "active, so it was not run.")  # fmt: skip
        source = jobs.job_file(settings, upload)
        estimate = estimate_rows(source, job.input_format)
        if estimate > settings.max_rows:
            return fail(jobs.FAILED, f"The file has {estimate:,} rows, but one job accepts at "
                                     f"most {settings.max_rows:,}. Please split it.")  # fmt: skip
        jobs.report_progress(url, job.id, worker_id, rows_total=estimate,
                             audit_batch_id=audit_batch_id, audited=audit_on)  # fmt: skip
        policy = load_profile(job.profile)
        artifact = artifact or model_mod.load_artifact()
        outputs = pipeline.Outputs(*(jobs.job_file(settings, n) for n in names.values()))
        context = (
            pipeline.AuditContext(
                url=url,
                user_ref=job.created_by,
                actor_role="manager",
                request_id=job.id,
                batch_id=audit_batch_id,
                chunk_size=settings.audit_chunk_size,
            )  # fmt: skip
            if audit_on
            else None
        )

        def on_chunk(progress: pipeline.Progress) -> None:
            state["audited"] = progress.audited
            owned, cancel = jobs.report_progress(
                url, job.id, worker_id, rows_processed=progress.total_rows,
                rows_skipped=progress.invalid_rows, rows_audited=progress.audited,
                approved=progress.approved, rejected=progress.rejected,
                borderline=progress.borderline,
            )  # fmt: skip
            if not owned or cancel:
                raise pipeline.Cancelled()

        progress = pipeline.run_file(
            source, outputs, policy, artifact, chunk_size=settings.chunk_size,
            include_positive=job.include_positive, audit_context=context,
            max_rows=settings.max_rows, on_chunk=on_chunk, fmt=job.input_format,
        )  # fmt: skip
        summary = progress.summary()
        note = None
        try:
            storage.save_summary(
                summary,
                str(artifact.get("version", "unknown")),
                _stored_rows(settings, names["result_path"]),
                load_policy(),
            )
        except Exception:  # noqa: BLE001 - the summary must not fail the job
            note = "The results are complete, but the anonymised summary was not saved."
        if not audit_on:
            note = ((note + " ") if note else "") + (
                "Audit records were switched off for this job (LOANLENS_BATCH_AUDIT=off)."
            )
        jobs.finish(
            url, job.id, worker_id, jobs.COMPLETED,
            rows_total=progress.total_rows, rows_processed=progress.total_rows,
            rows_skipped=progress.invalid_rows, rows_audited=progress.audited,
            approved=progress.approved, rejected=progress.rejected,
            borderline=progress.borderline, summary=json.dumps(_json_safe(summary)),
            error_message=note, upload_path=None, **names,
        )  # fmt: skip
        return jobs.COMPLETED
    except pipeline.Cancelled:
        return fail(jobs.CANCELLED, "Cancelled while running.")
    except BatchError as exc:
        return fail(jobs.FAILED, str(exc))
    except DatabaseError:
        return fail(jobs.FAILED, "The database could not be reached, so the job stopped.")
    except Exception as exc:  # noqa: BLE001 - never crash the worker; never log applicant data
        logger.error(
            "job_failed", extra={"fields": {"job_id": job.id, "error_type": type(exc).__name__}}
        )
        try:
            return fail(jobs.FAILED, "Something went wrong while processing the file.")
        except Exception:  # noqa: BLE001 - database down as well
            return jobs.FAILED
    finally:
        jobs.remove_file(settings, upload)


def _json_safe(summary: dict[str, Any]) -> dict[str, Any]:
    rate = summary.get("approval_rate")
    return {**summary, "approval_rate": None if rate is None or rate != rate else rate}


def _stored_rows(settings: jobs.JobSettings, result_name: str):
    """Per-row results for ``store_applicant_ids`` (read back in batches, only if enabled)."""
    if not load_policy().storage.store_applicant_ids:
        return None
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(jobs.job_file(settings, result_name))
    cols = ["applicant_id", "status", "probability"]
    return (b.to_pandas() for b in parquet.iter_batches(batch_size=50_000, columns=cols))


def work_once(
    url: str | None = None,
    *,
    worker_id: str | None = None,
    settings: jobs.JobSettings | None = None,
    artifact: dict[str, Any] | None = None,
) -> str | None:
    """Claim and run one queued job; returns its id, or None when the queue is empty."""
    url = url or _url()
    settings = settings or jobs.load_job_settings()
    worker_id = worker_id or new_worker_id(jobs.EXTERNAL)
    job = jobs.claim_next(url, worker_id)
    if job is None:
        return None
    process(job, url=url, worker_id=worker_id, settings=settings, artifact=artifact)
    return job.id


def startup(url: str, settings: jobs.JobSettings) -> None:
    """Start-up housekeeping: fail stale running jobs and delete expired files."""
    jobs.mark_stale(url, settings.stale_seconds, settings)
    jobs.expire_old(url, settings)


class Worker:
    """A polling worker loop; ``run()`` blocks until :meth:`stop` is called."""

    def __init__(self, kind: str = jobs.EXTERNAL, url: str | None = None,
                 settings: jobs.JobSettings | None = None) -> None:  # fmt: skip
        self.kind = kind
        self.url = url or _url()
        self.settings = settings or jobs.load_job_settings()
        self.id = new_worker_id(kind)
        self._stop = threading.Event()
        self._artifact: dict[str, Any] | None = None

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _heartbeat(self, finished: threading.Event) -> None:
        """Report this worker as alive every poll interval, also while a long job runs."""
        while not finished.wait(self.settings.poll_seconds):
            try:
                jobs.touch_worker(self.url, self.id, self.kind)
            except Exception:  # noqa: BLE001 - a missed heartbeat is retried next time
                pass

    def run(self, once: bool = False) -> int:
        """Process jobs until stopped (or, with ``once``, until the queue is empty)."""
        done = 0
        last_check = 0.0
        finished = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(finished,),
                                name="loanlens-worker-heartbeat", daemon=True)  # fmt: skip
        try:
            jobs.touch_worker(self.url, self.id, self.kind)
            beat.start()
            startup(self.url, self.settings)
            while not self._stop.is_set():
                jobs.touch_worker(self.url, self.id, self.kind)
                if time.monotonic() - last_check > STALE_CHECK_SECONDS:
                    jobs.mark_stale(self.url, self.settings.stale_seconds, self.settings)
                    last_check = time.monotonic()
                self._artifact = self._artifact or model_mod.load_artifact()
                job_id = work_once(self.url, worker_id=self.id, settings=self.settings,
                                   artifact=self._artifact)  # fmt: skip
                if job_id is not None:
                    done += 1
                    continue
                if once:
                    break
                self._stop.wait(self.settings.poll_seconds)
        except DatabaseError:
            logger.error("worker_stopped", extra={"fields": {"reason": "database_unavailable"}})
        finally:
            finished.set()
            if beat.is_alive():
                beat.join(5)
            try:
                jobs.remove_worker(self.url, self.id)
            except Exception:  # noqa: BLE001
                pass
        return done


_embedded: dict[str, tuple[Worker, threading.Thread]] = {}
_embedded_lock = threading.Lock()


def ensure_worker(url: str | None = None, settings: jobs.JobSettings | None = None) -> str:
    """Make sure some worker will pick up jobs; returns ``external``, ``embedded`` or ``none``.

    Starts one embedded daemon thread per database per process when no external worker
    has reported in recently and ``LOANLENS_EMBEDDED_WORKER`` is on.
    """
    url = url or _url()
    settings = settings or jobs.load_job_settings()
    with _embedded_lock:
        current = _embedded.get(url)
        if current is not None and current[1].is_alive():
            return jobs.EMBEDDED
        within = max(settings.poll_seconds * HEARTBEAT_GRACE, 10.0)
        if jobs.external_worker_alive(url, within):
            return jobs.EXTERNAL
        if not settings.embedded_worker:
            return "none"
        worker = Worker(jobs.EMBEDDED, url, settings)
        thread = threading.Thread(target=worker.run, name="loanlens-embedded-worker",
                                  daemon=True)  # fmt: skip
        thread.start()
        _embedded[url] = (worker, thread)
        return jobs.EMBEDDED


def stop_embedded(timeout: float = 10.0) -> None:
    """Stop embedded workers (tests and shutdown)."""
    with _embedded_lock:
        items = list(_embedded.values())
        _embedded.clear()
    for worker, thread in items:
        worker.stop()
        thread.join(timeout)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m loanlens.worker",
                                     description="LoanLens batch job worker.")  # fmt: skip
    parser.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="delete job files older than the retention period, then exit",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        settings = jobs.load_job_settings()
        url = _url()
        if args.cleanup:
            expired = jobs.expire_old(url, settings)
            print(f"Expired {len(expired)} job(s); their files were deleted.")
            return 0
        worker = Worker(jobs.EXTERNAL, url, settings)
        print(f"Worker {worker.id} started. Press Ctrl+C to stop.")
        try:
            done = worker.run(once=args.once)
        except KeyboardInterrupt:
            worker.stop()
            done = 0
        print(f"Worker stopped after {done} job(s).")
        return 0
    except (ConfigurationError, DatabaseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
