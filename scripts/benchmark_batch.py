"""Measure the batch job pipeline end to end on synthetic files (reports/performance.md).

Generates fully synthetic applicants (``loanlens.synthetic``: random values within the
model's training ranges; every ID starts with ``SYN-``) as CSV files in
``data/benchmarks/`` (gitignored), then runs each file through the real job path: a
manager account is created in a fresh database, the file is submitted through
``services.submit_batch_job`` (the upload is copied into the private jobs directory) and
processed by ``worker.work_once`` (chunked pipeline, audit records, result files, summary).

Each configuration runs in its own Python process so that peak memory is measured cleanly.
Measured per run: wall time from submission to completion (model already loaded), rows per
second, and peak resident memory of the process (psutil, sampled every 20 ms).

Usage::

    python scripts/benchmark_batch.py                       # 100k, 500k, 1M; SQLite and
                                                            # PostgreSQL if available; audit on/off
    python scripts/benchmark_batch.py --sizes 100000 --backends sqlite

PostgreSQL runs use ``LOANLENS_TEST_POSTGRES_URL`` (a disposable database: its LoanLens
tables are dropped before every run). Without it, PostgreSQL is reported as not measured.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "data" / "benchmarks"
RESULTS = BENCH_DIR / "results.jsonl"
PG_ENV = "LOANLENS_TEST_POSTGRES_URL"
SIZES = (100_000, 500_000, 1_000_000)
PACKAGES = ("pandas", "numpy", "pyarrow", "xgboost", "shap", "scikit-learn", "SQLAlchemy",
            "psycopg", "psutil")  # fmt: skip
TABLES = ("batch_workers", "batch_jobs", "decision_audit", "auth_events", "users", "batch_rows",
          "batch_summaries", "alembic_version")  # fmt: skip


def machine() -> dict:
    """Hardware and software of this machine."""
    import psutil

    cpu = platform.processor()
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()  # fmt: skip
            cpu = out or cpu
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "cpu": cpu,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python": platform.python_version(),
        "packages": {p: metadata.version(p) for p in PACKAGES},
    }


def dataset(rows: int) -> Path:
    """The synthetic CSV for ``rows`` (generated once, then reused)."""
    from loanlens import synthetic

    path = BENCH_DIR / f"synthetic_{rows}.csv"
    if not path.exists():
        synthetic.write_csv(path, rows)
    return path


def _drop_postgres(url: str) -> None:
    from sqlalchemy import text

    from loanlens.db import engine as db_engine

    with db_engine.get_engine(url).begin() as conn:
        for table in TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        conn.execute(text("DROP FUNCTION IF EXISTS decision_audit_append_only() CASCADE"))
    db_engine.reset_caches()


def single(rows: int, backend: str, audit: str) -> dict:
    """One measured run in this process (call in a fresh process)."""
    run_dir = BENCH_DIR / "run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    if backend == "sqlite":
        url = f"sqlite:///{(run_dir / 'bench.sqlite').as_posix()}"
    else:
        url = os.environ[PG_ENV]
    os.environ.update({
        "DATABASE_URL": url, "LOANLENS_JOBS_DIR": str(run_dir / "jobs"),
        "LOANLENS_BATCH_AUDIT": "row" if audit == "on" else "off",
        "LOANLENS_EMBEDDED_WORKER": "0", "LOANLENS_JWT_SECRET": secrets.token_urlsafe(48),
    })  # fmt: skip
    for name in ("LOANLENS_ENV", "LOANLENS_HOSTED", "LOANLENS_JOB_CHUNK_SIZE"):
        os.environ.pop(name, None)

    import psutil
    from sqlalchemy import func, select

    from loanlens import auth, jobs, model, services, worker
    from loanlens.db.engine import normalise_url, session_scope
    from loanlens.db.models import DecisionAudit

    if backend == "postgresql":
        _drop_postgres(normalise_url(url))
    source = dataset(rows)
    password = "Bench-" + secrets.token_urlsafe(16)  # throwaway account, never stored
    email = f"bench-{secrets.token_hex(4)}@example.com"
    auth.create_manager_account(email, password)
    principal = auth.sign_in(email, password).principal
    artifact = model.load_artifact()
    settings = jobs.load_job_settings()

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
    start = time.perf_counter()
    with open(source, "rb") as fh:
        job = services.submit_batch_job(principal, fh, source.name)
    submitted = time.perf_counter()
    worker.work_once(settings=settings, artifact=artifact)
    end = time.perf_counter()
    stop.set()
    sampler.join()

    done = services.get_batch_job(principal, job.id)
    with session_scope(services._url()) as session:
        audited = session.execute(select(func.count()).select_from(DecisionAudit)).scalar()
    wall = end - start
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": rows, "backend": backend, "audit": audit, "status": done.status,
        "chunk_size": settings.chunk_size, "scored": done.approved + done.rejected,
        "skipped": done.rows_skipped, "audit_rows_in_db": int(audited),
        "wall_seconds": round(wall, 2), "submit_seconds": round(submitted - start, 2),
        "rows_per_second": round(rows / wall, 1),
        "peak_rss_mb": round(peak[0] / 1024**2, 1), "start_rss_mb": round(base / 1024**2, 1),
        "peak_growth_mb": round((peak[0] - base) / 1024**2, 1),
        "approved": done.approved, "rejected": done.rejected,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--backends", nargs="+", default=["sqlite", "postgresql"],
                        choices=["sqlite", "postgresql"])  # fmt: skip
    parser.add_argument("--audit", nargs="+", default=["on", "off"], choices=["on", "off"])
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.single:
        print(json.dumps(single(args.sizes[0], args.backends[0], args.audit[0])))
        return 0

    print(json.dumps({"machine": machine()}, indent=2))
    backends = list(args.backends)
    if "postgresql" in backends and not os.environ.get(PG_ENV):
        print(f"PostgreSQL not measured: {PG_ENV} is not set.")
        backends.remove("postgresql")
    for rows in args.sizes:
        dataset(rows)  # generate outside the timed runs
    for backend in backends:
        for rows in args.sizes:
            for audit in args.audit:
                cmd = [sys.executable, __file__, "--single", "--sizes", str(rows),
                       "--backends", backend, "--audit", audit]  # fmt: skip
                out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
                line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
                if out.returncode != 0 or not line.startswith("{"):
                    print(f"FAILED {backend} {rows} audit={audit}: exit {out.returncode}")
                    print(out.stderr[-2000:])
                    continue
                result = json.loads(line)
                with open(RESULTS, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                print(f"{backend:10} {rows:>9,} audit={audit:3} {result['status']:9} "
                      f"{result['wall_seconds']:>8.1f} s {result['rows_per_second']:>8.0f} rows/s "
                      f"peak {result['peak_rss_mb']:>7.0f} MB", flush=True)  # fmt: skip
    shutil.rmtree(BENCH_DIR / "run", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
