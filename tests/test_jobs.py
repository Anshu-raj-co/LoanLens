"""Milestone 4: chunked pipeline, background jobs, worker, file safety and memory bound.

The job-claiming tests run on SQLite always and on PostgreSQL (``SELECT ... FOR UPDATE SKIP
LOCKED``) when ``LOANLENS_TEST_POSTGRES_URL`` points at a disposable database (its tables
are dropped); otherwise the PostgreSQL case is skipped.
"""

from __future__ import annotations

import io
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import pytest
from app_support import new_session
from sqlalchemy import select, text, update

from loanlens import audit, auth, batch, jobs, pipeline, services, storage, synthetic, worker
from loanlens.audit import AuditFilters
from loanlens.auth.settings import ConfigurationError
from loanlens.config import load_policy
from loanlens.db import engine as db_engine
from loanlens.db.engine import DatabaseError, normalise_url, session_scope
from loanlens.db.models import BatchJob

PG_ENV = "LOANLENS_TEST_POSTGRES_URL"
FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "batch_1000.csv"
EXPECTED = FIXTURES / "batch_1000_expected.csv"
EXPECTED_ERRORS = FIXTURES / "batch_1000_expected_errors.csv"
POLICY = load_policy()
TEXT_COLUMNS = ["row", "applicant_id", "product", "status", "likelihood", "borderline",
                "reasons", "what_would_change", "warnings", "reason_codes"]  # fmt: skip


def _outputs(tmp_path: Path, tag: str = "r") -> pipeline.Outputs:
    return pipeline.Outputs(tmp_path / f"{tag}.parquet", tmp_path / f"{tag}.csv",
                            tmp_path / f"{tag}_errors.csv")  # fmt: skip


def _run(path: Path, tmp_path: Path, artifact, chunk_size: int, tag: str = "r", **kw):
    out = _outputs(tmp_path, tag)
    progress = pipeline.run_file(path, out, POLICY, artifact, chunk_size=chunk_size, **kw)
    return progress, out


def _expected() -> pd.DataFrame:
    return pd.read_csv(EXPECTED, keep_default_na=False)


def _assert_same_as_previous_path(results: pd.DataFrame) -> None:
    """Identical to the Milestone 3 in-memory batch path (golden file from before M4)."""
    expected = _expected()
    assert len(results) == len(expected) == 980
    for col in TEXT_COLUMNS:
        assert results[col].astype(str).tolist() == expected[col].astype(str).tolist(), col
    np.testing.assert_allclose(results["probability"], expected["probability"], atol=1e-6, rtol=0)


def _manager():
    return new_session(auth.MANAGER).principal


def _submit(principal, data: bytes, name: str = "upload.csv", **kw) -> jobs.JobView:
    return services.submit_batch_job(principal, io.BytesIO(data), name, **kw)


# ---- Pipeline: identical decisions, chunk boundaries, bad rows, Parquet ---------------------


@pytest.mark.parametrize("chunk_size", [37, 999, 1000, 1001, 20_000])
def test_chunked_results_identical_to_previous_batch_path(tmp_path, artifact, chunk_size) -> None:
    progress, out = _run(FIXTURE, tmp_path, artifact, chunk_size)
    _assert_same_as_previous_path(pd.read_parquet(out.results_parquet))
    _assert_same_as_previous_path(pd.read_csv(out.results_csv, keep_default_na=False))
    assert progress.chunks == -(-1000 // chunk_size)
    assert (progress.total_rows, progress.valid_rows, progress.invalid_rows) == (1000, 980, 20)


def test_bad_rows_across_chunks_keep_original_row_numbers(tmp_path, artifact) -> None:
    _, out = _run(FIXTURE, tmp_path, artifact, 37)
    errors = pd.read_csv(out.errors_csv, keep_default_na=False)
    expected = pd.read_csv(EXPECTED_ERRORS, keep_default_na=False)
    pd.testing.assert_frame_equal(errors.astype(str), expected.astype(str))
    rows = errors["row"].tolist()
    assert len({(r - 2) // 37 for r in rows}) > 10  # spread over many chunks


def test_a_chunk_of_only_bad_rows(tmp_path, artifact) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()), dtype=str)
    bad = frame.assign(cibil_score="abc")
    data = pd.concat([bad, bad, frame], ignore_index=True)  # chunk 1 and 2 invalid
    path = tmp_path / "in.csv"
    data.to_csv(path, index=False)
    progress, out = _run(path, tmp_path, artifact, 3)
    results = pd.read_parquet(out.results_parquet)
    assert results["row"].tolist() == [8, 9, 10] and progress.invalid_rows == 6
    errors = pd.read_csv(out.errors_csv)
    assert errors["row"].tolist() == [2, 3, 4, 5, 6, 7]


def test_summary_matches_previous_summary(tmp_path, artifact) -> None:
    progress, _ = _run(FIXTURE, tmp_path, artifact, 300)
    parsed = batch.parse_upload(FIXTURE.read_bytes())
    old = batch.summarise(batch.score(parsed, artifact=artifact), parsed)
    new = progress.summary()
    for key in ("total_rows", "valid_rows", "invalid_rows", "approved", "rejected",
                "borderline", "approval_rate", "top_rejection_reasons"):  # fmt: skip
        assert new[key] == old[key], key
    assert new["likelihood_bands"] == old["likelihood_bands"]


def test_parquet_input_gives_identical_results(tmp_path, artifact) -> None:
    text_frame = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    text_frame.to_parquet(tmp_path / "in.parquet")
    assert batch.detect_format(tmp_path / "in.parquet") == batch.PARQUET_FORMAT
    assert batch.estimate_rows(tmp_path / "in.parquet") == 1000
    _, out = _run(tmp_path / "in.parquet", tmp_path, artifact, 333)
    _assert_same_as_previous_path(pd.read_parquet(out.results_parquet))


def test_parquet_with_numeric_columns_and_aliases(tmp_path, artifact) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()))
    frame = frame.rename(columns={"cibil_score": "CIBIL", "income_annum": "Annual Income"})
    frame["loan_term"] = frame["loan_term"].astype(float)
    frame.loc[1, "bank_asset_value"] = np.nan  # blank cell: an error, never a zero
    frame.to_parquet(tmp_path / "num.parquet")
    progress, out = _run(tmp_path / "num.parquet", tmp_path, artifact, 2)
    results = pd.read_parquet(out.results_parquet)
    assert results["status"].tolist() == ["Approved", "Rejected"]
    errors = pd.read_csv(out.errors_csv)
    assert errors["row"].tolist() == [3] and "missing" in errors["problem"][0]
    assert progress.invalid_rows == 1


def test_unreadable_and_bad_files(tmp_path, artifact) -> None:
    cases = {
        "empty.csv": b"   ",
        "binary.csv": b"\x00\x01\x02\xff\xfe" * 50,
        "header_only.csv": ",".join(batch.REQUIRED_COLUMNS).encode(),
        "missing.csv": b"cibil_score,income_annum\n700,5000000\n",
        "fake.parquet": batch.PARQUET_MAGIC + b"not really parquet",
    }
    for name, data in cases.items():
        (tmp_path / name).write_bytes(data)
        with pytest.raises(batch.BatchError):
            _run(tmp_path / name, tmp_path, artifact, 100, tag=name)


def test_malformed_line_part_way_fails_with_a_plain_message(tmp_path, artifact) -> None:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    lines.insert(600, lines[600] + ",1,2,3")  # too many fields part-way through
    (tmp_path / "bad.csv").write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(batch.BatchError, match="same number of columns"):
        _run(tmp_path / "bad.csv", tmp_path, artifact, 100)


def test_cp1252_and_semicolon_files(tmp_path, artifact) -> None:
    frame = pd.read_csv(io.BytesIO(batch.template_csv()), dtype=str)
    frame["applicant_id"] = ["Café-1", "Café-2", "Café-3"]
    path = tmp_path / "cp.csv"
    path.write_bytes(frame.to_csv(index=False, sep=";").encode("cp1252"))
    assert batch.detect_encoding(path) == "cp1252"
    _, out = _run(path, tmp_path, artifact, 2)
    assert (
        pd.read_parquet(out.results_parquet)["applicant_id"].tolist()
        == frame["applicant_id"].tolist()
    )


def test_row_limit(tmp_path, artifact) -> None:
    with pytest.raises(batch.BatchError, match="more than 500 rows"):
        _run(FIXTURE, tmp_path, artifact, 300, max_rows=500)


def test_audit_rows_written_per_chunk(tmp_path, artifact) -> None:
    manager = _manager()
    url = storage.resolve_url()
    context = pipeline.AuditContext(
        url=url,
        user_ref=manager.audit_ref,
        actor_role="manager",
        request_id="req-1",
        batch_id=audit.new_id(),
        chunk_size=64,
    )
    seen: list[int] = []
    progress, _ = _run(FIXTURE, tmp_path, artifact, 250, audit_context=context,
                       on_chunk=lambda p: seen.append(p.audited))  # fmt: skip
    assert progress.audited == 980 and seen[-1] == 980 and seen == sorted(seen)
    assert services.audit_records(manager, AuditFilters(channel="batch")).total == 980


def test_storage_accepts_results_in_frames(tmp_path) -> None:
    policy = POLICY.model_copy(
        update={"storage": POLICY.storage.model_copy(update={"store_applicant_ids": True})}
    )
    frames = [
        pd.DataFrame({"applicant_id": ["A"], "status": ["Approved"], "probability": [0.9]}),
        pd.DataFrame(columns=["applicant_id", "status", "probability"]),
        pd.DataFrame({"applicant_id": ["B"], "status": ["Rejected"], "probability": [0.1]}),
    ]
    summary = {"total_rows": 2, "valid_rows": 2, "invalid_rows": 0, "approved": 1,
               "rejected": 1, "borderline": 0, "approval_rate": 0.5}  # fmt: skip
    batch_id = storage.save_summary(summary, "1.0.0", iter(frames), policy, path=tmp_path / "s.db")
    with session_scope(db_engine.sqlite_url(tmp_path / "s.db")) as session:
        count = session.execute(
            text("SELECT COUNT(*) FROM batch_rows WHERE batch_id = :b"), {"b": batch_id}
        ).scalar()
    assert count == 2


# ---- Settings and file safety ------------------------------------------------------------------


def test_job_settings_defaults_and_validation(tmp_path) -> None:
    s = jobs.load_job_settings({})
    assert (s.chunk_size, s.max_rows, s.max_upload_mb, s.retention_days, s.audit) == (
        20_000,
        1_000_000,
        200,
        7,
        "row",
    )
    assert s.embedded_worker and s.jobs_dir == jobs.DEFAULT_JOBS_DIR
    s = jobs.load_job_settings({jobs.ENV_EMBEDDED: "off", jobs.ENV_JOBS_DIR: "data/x",
                                jobs.ENV_CHUNK: "500"})  # fmt: skip
    assert not s.embedded_worker and s.chunk_size == 500 and s.jobs_dir.is_absolute()
    with pytest.raises(ConfigurationError, match=jobs.ENV_CHUNK):
        jobs.load_job_settings({jobs.ENV_CHUNK: "5"})
    with pytest.raises(ConfigurationError, match=jobs.ENV_AUDIT):
        jobs.load_job_settings({jobs.ENV_AUDIT: "maybe"})
    assert jobs.load_job_settings({jobs.ENV_AUDIT: "off"}).audit == "off"
    with pytest.raises(ConfigurationError, match="benchmarks only"):
        jobs.load_job_settings({jobs.ENV_AUDIT: "off", "LOANLENS_HOSTED": "1"})


def test_stored_names_are_random_and_paths_are_never_from_input(tmp_path) -> None:
    settings = jobs.load_job_settings()
    names = {jobs.new_file_name("csv") for _ in range(50)}
    assert len(names) == 50 and all(n.endswith(".csv") and len(n) == 36 for n in names)
    with pytest.raises(ValueError):
        jobs.new_file_name("exe")
    bad_names = [
        "../secret.csv",
        "..\\x.csv",
        "/etc/passwd",
        "a" * 32 + ".csv/../x",
        "C:\\Windows\\win.ini",
        "",
        None,
        "A" * 32 + ".csv",
        "a" * 32 + ".txt",
    ]
    for bad in bad_names:
        with pytest.raises(jobs.JobFileUnavailable):
            jobs.job_file(settings, bad)
    ok = jobs.job_file(settings, "0" * 32 + ".csv")
    assert ok.parent == Path(settings.jobs_dir).resolve()
    jobs.remove_file(settings, "../not-allowed.csv")  # ignored, never raises


def test_display_name_strips_paths_and_control_characters() -> None:
    assert jobs.display_name("../../evil name.csv") == "evil name.csv"
    assert jobs.display_name("C:\\Users\\x\\file.csv") == "file.csv"
    assert jobs.display_name("a\x00b\nc.csv") == "abc.csv"
    assert jobs.display_name("") == "upload"
    assert len(jobs.display_name("x" * 500)) == 120


def test_upload_limit_and_empty_upload(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(jobs.ENV_MAX_UPLOAD_MB, "1")
    settings = jobs.load_job_settings()
    with pytest.raises(jobs.UploadTooLarge, match="larger than 1 MB"):
        jobs.save_upload(settings, io.BytesIO(b"x" * (1024 * 1024 + 1)))
    with pytest.raises(batch.BatchError, match="empty"):
        jobs.save_upload(settings, io.BytesIO(b""))
    assert list(Path(settings.jobs_dir).iterdir()) == []  # no partial files left
    name, fmt = jobs.save_upload(settings, io.BytesIO(batch.PARQUET_MAGIC + b"rest"))
    assert fmt == "parquet" and name.endswith(".parquet")


# ---- Job lifecycle ------------------------------------------------------------------------------


def test_job_lifecycle(artifact) -> None:
    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes(), "../applicants.csv", product="home")
    assert job.status == jobs.QUEUED and job.filename == "applicants.csv"
    assert job.created_by == manager.audit_ref and job.profile == "home"
    settings = jobs.load_job_settings()
    upload = Path(settings.jobs_dir) / jobs.get_row(storage.resolve_url(), job.id).upload_path
    assert upload.exists()
    with pytest.raises(jobs.JobFileUnavailable, match="once the job has completed"):
        services.batch_job_file(manager, job.id, "result")
    assert worker.work_once(artifact=artifact) == job.id
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.COMPLETED and done.fraction == 1.0
    assert (done.rows_total, done.rows_processed, done.rows_skipped) == (1000, 1000, 20)
    assert done.approved + done.rejected == 980 == done.rows_audited
    assert done.started_at <= done.finished_at and done.audited
    assert done.summary["valid_rows"] == 980 and done.audit_batch_id
    assert not upload.exists()  # the upload is deleted when the job ends
    results = pd.read_parquet(services.batch_job_file(manager, job.id, "result"))
    assert set(results["product"]) == {"home"}
    assert len(services.batch_job_preview(manager, job.id, "result", 10)) == 10
    assert len(services.batch_job_preview(manager, job.id, "errors")) == 20
    with pytest.raises(jobs.JobFileUnavailable):
        services.batch_job_file(manager, job.id, "anything")
    assert worker.work_once(artifact=artifact) is None  # queue empty
    other = _manager()  # any manager may see every job (documented)
    assert [j.id for j in services.list_batch_jobs(other)] == [job.id]


def test_unknown_job_and_bad_ids(artifact) -> None:
    manager = _manager()
    for bad in ("nope", "../x", str(__import__("uuid").uuid4())):
        with pytest.raises(jobs.JobNotFound):
            services.get_batch_job(manager, bad)
        with pytest.raises(jobs.JobNotFound):
            services.batch_job_file(manager, bad, "result")
        with pytest.raises(jobs.JobNotFound):
            services.cancel_batch_job(manager, bad)


def test_cancel_a_queued_job(artifact) -> None:
    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    cancelled = services.cancel_batch_job(manager, job.id)
    assert cancelled.status == jobs.CANCELLED and cancelled.finished_at
    assert worker.work_once(artifact=artifact) is None
    assert services.audit_records(manager).total == 0


def test_cancel_a_running_job_keeps_audited_rows(monkeypatch, artifact) -> None:
    monkeypatch.setenv(jobs.ENV_CHUNK, "300")
    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    url = storage.resolve_url()
    real = jobs.report_progress

    def cancel_after_first_chunk(url_, job_id, worker_id, **counts):
        if counts.get("rows_processed"):
            jobs.request_cancel(url_, job_id)
        return real(url_, job_id, worker_id, **counts)

    monkeypatch.setattr(jobs, "report_progress", cancel_after_first_chunk)
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.CANCELLED and not done.has_result
    assert done.rows_audited == 294  # first chunk: 300 rows, 6 of them invalid
    assert done.audit_batch_id in done.error_message and "new batch id" in done.error_message
    assert services.audit_records(manager, AuditFilters(channel="batch")).total == 294
    assert sorted(os.listdir(jobs.load_job_settings().jobs_dir)) == []  # partial files removed
    assert services.cancel_batch_job(manager, job.id).status == jobs.CANCELLED  # unchanged
    del url


def test_job_with_missing_columns_fails_plainly(artifact) -> None:
    manager = _manager()
    job = _submit(manager, b"cibil_score,income_annum\n700,5000000\n")
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.FAILED and "Required columns are missing" in done.error_message
    assert "No rows were recorded" in done.error_message


def test_job_over_the_row_limit_fails(monkeypatch, artifact) -> None:
    monkeypatch.setenv(jobs.ENV_MAX_ROWS, "999")
    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.FAILED and "at most 999" in done.error_message


def test_job_fails_when_audit_cannot_be_written(monkeypatch, artifact) -> None:
    def broken(*_a, **_k):
        raise DatabaseError()

    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    monkeypatch.setattr(audit, "write", broken)
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.FAILED and "database could not be reached" in done.error_message
    assert not done.has_result


def test_unexpected_error_fails_the_job_without_details(monkeypatch, artifact) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("secret internals")

    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    monkeypatch.setattr(pipeline, "run_file", boom)
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.FAILED and "secret" not in done.error_message


def test_job_of_a_deactivated_manager_is_not_run(artifact) -> None:
    first, second = new_session(auth.MANAGER), new_session(auth.MANAGER)
    job = _submit(second.principal, FIXTURE.read_bytes())
    auth.set_active(first.principal, second.principal.user_id, False)
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(first.principal, job.id)
    assert done.status == jobs.FAILED and "no longer active" in done.error_message
    assert services.audit_records(first.principal).total == 0


def test_audit_off_is_recorded_on_the_job(monkeypatch, artifact) -> None:
    monkeypatch.setenv(jobs.ENV_AUDIT, "off")
    manager = _manager()
    job = _submit(manager, FIXTURE.read_bytes())
    worker.work_once(artifact=artifact)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.COMPLETED and not done.audited and done.rows_audited == 0
    assert "LOANLENS_BATCH_AUDIT=off" in done.error_message
    assert services.audit_records(manager).total == 0


def test_parquet_job_end_to_end(tmp_path, artifact) -> None:
    pd.read_csv(FIXTURE, dtype=str, keep_default_na=False).to_parquet(tmp_path / "f.parquet")
    manager = _manager()
    job = _submit(manager, (tmp_path / "f.parquet").read_bytes(), "f.parquet")
    assert job.input_format == "parquet"
    worker.work_once(artifact=artifact)
    _assert_same_as_previous_path(
        pd.read_parquet(services.batch_job_file(manager, job.id, "result"))
    )


# ---- Stale jobs, retention, workers ------------------------------------------------------------


def _age(url: str, job_id: str, **fields) -> None:
    with session_scope(url) as session:
        session.execute(update(BatchJob).where(BatchJob.id == job_id).values(**fields))


def test_stale_running_jobs_are_failed_at_startup(artifact) -> None:
    manager = _manager()
    url = storage.resolve_url()
    settings = jobs.load_job_settings()
    job = _submit(manager, FIXTURE.read_bytes())
    claimed = jobs.claim_next(url, "dead-worker")
    assert claimed.id == job.id
    jobs.report_progress(url, job.id, "dead-worker", rows_audited=40, audit_batch_id="b-1")
    assert jobs.mark_stale(url, settings.stale_seconds, settings) == []  # fresh heartbeat
    _age(url, job.id, heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
    worker.startup(url, settings)
    done = services.get_batch_job(manager, job.id)
    assert done.status == jobs.FAILED and "stopped unexpectedly" in done.error_message
    assert "40 rows were already recorded" in done.error_message and "b-1" in done.error_message
    assert jobs.get_row(url, job.id).upload_path is None
    owned, _ = jobs.report_progress(url, job.id, "dead-worker", rows_processed=5)
    assert not owned  # the old worker can no longer write to it
    assert not jobs.finish(url, job.id, "dead-worker", jobs.COMPLETED)
    with pytest.raises(ValueError):
        jobs.finish(url, job.id, "dead-worker", jobs.QUEUED)


def test_retention_cleanup_deletes_files_and_marks_jobs_expired(artifact, capsys) -> None:
    manager = _manager()
    url = storage.resolve_url()
    settings = jobs.load_job_settings()
    done_job = _submit(manager, FIXTURE.read_bytes())
    worker.work_once(artifact=artifact)
    queued = _submit(manager, FIXTURE.read_bytes())
    row = jobs.get_row(url, done_job.id)
    files = [jobs.job_file(settings, n) for n in (row.result_path, row.result_csv_path,
                                                  row.errors_path)]  # fmt: skip
    assert all(f.exists() for f in files)
    assert worker.main(["--cleanup"]) == 0 and "Expired 0 job(s)" in capsys.readouterr().out
    old = datetime.now(UTC) - timedelta(days=settings.retention_days + 1)
    _age(url, done_job.id, finished_at=old)
    _age(url, queued.id, created_at=old)
    assert worker.main(["--cleanup"]) == 0 and "Expired 2 job(s)" in capsys.readouterr().out
    assert not any(f.exists() for f in files)
    assert list(Path(settings.jobs_dir).iterdir()) == []
    expired = services.get_batch_job(manager, done_job.id)
    assert expired.status == jobs.EXPIRED and "retention" in expired.error_message
    with pytest.raises(jobs.JobFileUnavailable, match="retention period"):
        services.batch_job_file(manager, done_job.id, "result")


def test_worker_command_line_once(artifact, capsys) -> None:
    manager = _manager()
    job = _submit(manager, batch.template_csv())
    assert worker.main(["--once"]) == 0
    assert "after 1 job(s)" in capsys.readouterr().out
    assert services.get_batch_job(manager, job.id).status == jobs.COMPLETED


def test_worker_command_line_reports_bad_settings(monkeypatch, capsys) -> None:
    monkeypatch.setenv(jobs.ENV_CHUNK, "nope")
    assert worker.main(["--once"]) == 2
    assert "Invalid setting" in capsys.readouterr().err


def test_embedded_worker_runs_jobs_and_defers_to_an_external_one(monkeypatch, artifact) -> None:
    url = storage.resolve_url()
    off = jobs.load_job_settings()
    assert worker.ensure_worker(url, off) == "none"  # tests switch it off by default
    jobs.touch_worker(url, "external-test", jobs.EXTERNAL)
    assert worker.ensure_worker(url, off) == jobs.EXTERNAL
    jobs.remove_worker(url, "external-test")
    monkeypatch.setenv(jobs.ENV_EMBEDDED, "1")
    monkeypatch.setenv(jobs.ENV_POLL, "0.05")
    on = jobs.load_job_settings()
    manager = _manager()
    job = _submit(manager, batch.template_csv())
    assert worker.ensure_worker(url, on) == jobs.EMBEDDED
    assert worker.ensure_worker(url, on) == jobs.EMBEDDED  # one thread per process
    deadline = time.monotonic() + 60
    while services.get_batch_job(manager, job.id).status != jobs.COMPLETED:
        assert time.monotonic() < deadline, "embedded worker did not finish the job"
        time.sleep(0.05)
    worker.stop_embedded()
    assert not jobs.external_worker_alive(url, 60)


def test_worker_loop_stops_cleanly() -> None:
    w = worker.Worker(jobs.EXTERNAL, storage.resolve_url(), jobs.load_job_settings())
    w.stop()
    assert w.stopped and w.run() == 0


# ---- Two workers never claim the same job (SQLite and PostgreSQL) ------------------------------


def _drop_postgres(url: str) -> None:
    db_engine.reset_caches()
    with db_engine.get_engine(url).begin() as conn:
        for table in (
            "batch_workers", "batch_jobs", "decision_audit", "auth_events", "users", "batch_rows",
            "batch_summaries", "alembic_version",
        ):  # fmt: skip
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.execute(text("DROP FUNCTION IF EXISTS decision_audit_append_only() CASCADE"))
    db_engine.reset_caches()


@pytest.fixture(params=["sqlite", "postgresql"])
def claim_db(request, tmp_path):
    if request.param == "sqlite":
        yield db_engine.sqlite_url(tmp_path / "claims.sqlite")
        return
    url = os.environ.get(PG_ENV)
    if not url:
        pytest.skip(f"set {PG_ENV} to run the PostgreSQL tests")
    url = normalise_url(url)
    _drop_postgres(url)
    yield url
    _drop_postgres(url)


def test_two_workers_never_claim_the_same_job(claim_db) -> None:
    n_jobs, n_workers = 40, 6
    for i in range(n_jobs):
        jobs.create_job(claim_db, created_by="ref", filename=f"f{i}.csv", profile="personal",
                        include_positive=False, input_format="csv",
                        upload_path=jobs.new_file_name("csv"))  # fmt: skip
    claimed: dict[str, list[str]] = {f"w{i}": [] for i in range(n_workers)}
    start = threading.Barrier(n_workers)

    def run(worker_id: str) -> None:
        start.wait()
        while (job := jobs.claim_next(claim_db, worker_id)) is not None:
            claimed[worker_id].append(job.id)

    threads = [threading.Thread(target=run, args=(w,)) for w in claimed]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    all_ids = [i for ids in claimed.values() for i in ids]
    assert len(all_ids) == n_jobs and len(set(all_ids)) == n_jobs  # every job exactly once
    with session_scope(claim_db) as session:
        rows = session.execute(select(BatchJob.id, BatchJob.worker_id, BatchJob.status)).all()
    owner = {job_id: w for w, ids in claimed.items() for job_id in ids}
    assert all(r.status == jobs.RUNNING and owner[r.id] == r.worker_id for r in rows)


def test_skip_locked_skips_a_row_being_claimed(claim_db) -> None:
    """While one transaction holds the oldest queued row, another claims the next one."""
    if db_engine.is_sqlite(claim_db):
        pytest.skip("SQLite has no row locks; its claim is a single conditional UPDATE")
    for i in range(2):
        jobs.create_job(claim_db, created_by="ref", filename=f"f{i}.csv", profile="personal",
                        include_positive=False, input_format="csv",
                        upload_path=jobs.new_file_name("csv"))  # fmt: skip
        time.sleep(0.01)
    oldest = jobs.list_jobs(claim_db)[-1].id
    engine = db_engine.get_engine(claim_db)
    with engine.connect() as holder:
        holder.execute(text("BEGIN"))
        locked = holder.execute(
            text(
                "SELECT id FROM batch_jobs WHERE status = 'queued' ORDER BY created_at, id "
                "LIMIT 1 FOR UPDATE"
            )  # fmt: skip
        ).scalar()
        assert locked == oldest
        other = jobs.claim_next(claim_db, "second")  # must not wait for the lock
        assert other is not None and other.id != oldest
        holder.execute(text("ROLLBACK"))
    assert jobs.claim_next(claim_db, "third").id == oldest


# ---- Memory bound ------------------------------------------------------------------------------

MEMORY_ROWS = 200_000
MEMORY_LIMIT_MB = 200  # measured growth on the development machine: about 99 MB


def test_memory_growth_is_bounded_on_a_200k_row_file(tmp_path, artifact) -> None:
    """Peak resident memory grows by less than MEMORY_LIMIT_MB while 200,000 rows stream
    through the pipeline in 20,000-row chunks (results go to disk, never all in memory)."""
    source = synthetic.write_csv(tmp_path / "synthetic_200k.csv", MEMORY_ROWS)
    _run(FIXTURE, tmp_path, artifact, 1000, tag="warm")  # warm up model and explainer
    proc = psutil.Process()
    base = proc.memory_info().rss
    peak = [base]
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss)
            time.sleep(0.02)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        progress, out = _run(source, tmp_path, artifact, 20_000)
    finally:
        stop.set()
        sampler.join()
    growth_mb = (peak[0] - base) / 1024 / 1024
    assert progress.total_rows == MEMORY_ROWS and progress.chunks == 10
    assert pd.read_parquet(out.results_parquet, columns=["row"])["row"].iloc[-1] == MEMORY_ROWS + 1
    assert growth_mb < MEMORY_LIMIT_MB, f"peak memory grew by {growth_mb:.0f} MB"


def test_synthetic_generator_is_marked_and_in_range() -> None:
    frame = synthetic.generate(5000, seed=1)
    assert frame["applicant_id"].str.startswith("SYN-").all()
    assert frame["cibil_score"].between(300, 900).all()
    assert set(frame["loan_term"]) <= set(range(2, 21, 2))
    ratio = frame["loan_amount"] / frame["income_annum"]
    assert ratio.between(1.3, 4.3).all()
    assert synthetic.generate(10, seed=1).equals(synthetic.generate(10, seed=1))
