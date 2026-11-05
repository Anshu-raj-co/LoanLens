"""SQLite storage of **anonymised** Bulk Check summaries (stdlib ``sqlite3``).

By default only aggregate counts are stored: no names, no applicant IDs and no input
values. Per-row applicant IDs and statuses are stored only if
``storage.store_applicant_ids`` is set to ``true`` in ``config/policy.yaml``.
Customer mode never writes here.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from loanlens.config import PROJECT_ROOT, Policy, load_policy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    total_rows INTEGER NOT NULL,
    valid_rows INTEGER NOT NULL,
    invalid_rows INTEGER NOT NULL,
    approved INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    borderline INTEGER NOT NULL,
    approval_rate REAL,
    likelihood_bands TEXT NOT NULL,
    top_rejection_reasons TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_rows (
    batch_id INTEGER NOT NULL REFERENCES batch_summaries(id),
    applicant_id TEXT,
    status TEXT NOT NULL,
    probability REAL NOT NULL
);
"""
SUMMARY_FIELDS = (
    "total_rows",
    "valid_rows",
    "invalid_rows",
    "approved",
    "rejected",
    "borderline",
    "approval_rate",
)


def db_path(policy: Policy | None = None) -> Path:
    """Database file from ``storage.db_path`` (relative paths are under the project root)."""
    policy = policy or load_policy()
    path = Path(policy.storage.db_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def save_summary(
    summary: dict[str, Any],
    model_version: str,
    results: pd.DataFrame | None = None,
    policy: Policy | None = None,
    path: Path | None = None,
) -> int:
    """Store one batch summary and return its id.

    Args:
        summary: output of :func:`loanlens.batch.summarise` (aggregates only).
        model_version: version string of the model used.
        results: per-row results; used only when ``store_applicant_ids`` is enabled.
        policy: policy (for the storage settings); defaults to ``config/policy.yaml``.
        path: database file; defaults to :func:`db_path`.
    """
    policy = policy or load_policy()
    path = path or db_path(policy)
    rate = summary.get("approval_rate")
    rate = None if rate is None or rate != rate else float(rate)  # NaN -> NULL
    with closing(_connect(path)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO batch_summaries (created_at, model_version, total_rows, valid_rows, "
            "invalid_rows, approved, rejected, borderline, approval_rate, likelihood_bands, "
            "top_rejection_reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                model_version,
                int(summary["total_rows"]),
                int(summary["valid_rows"]),
                int(summary["invalid_rows"]),
                int(summary["approved"]),
                int(summary["rejected"]),
                int(summary["borderline"]),
                rate,
                json.dumps(summary.get("likelihood_bands", {})),
                json.dumps(summary.get("top_rejection_reasons", [])),
            ),
        )
        batch_id = int(cur.lastrowid)
        if policy.storage.store_applicant_ids and results is not None and len(results):
            conn.executemany(
                "INSERT INTO batch_rows (batch_id, applicant_id, status, probability) "
                "VALUES (?, ?, ?, ?)",
                [
                    (batch_id, str(a), str(s), float(p))
                    for a, s, p in zip(
                        results["applicant_id"],
                        results["status"],
                        results["probability"],
                        strict=True,
                    )
                ],
            )
    return batch_id


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["likelihood_bands"] = json.loads(out["likelihood_bands"])
    out["top_rejection_reasons"] = json.loads(out["top_rejection_reasons"])
    return out


def latest_summary(path: Path | None = None) -> dict[str, Any] | None:
    """The most recent batch summary, or ``None`` if no batch has been stored."""
    path = path or db_path()
    if not path.exists():
        return None
    with closing(_connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM batch_summaries ORDER BY id DESC LIMIT 1").fetchone()
    return _row_to_dict(row) if row else None


def list_summaries(limit: int = 20, path: Path | None = None) -> pd.DataFrame:
    """Recent batch summaries (newest first) as a table."""
    path = path or db_path()
    if not path.exists():
        return pd.DataFrame(columns=["id", "created_at", *SUMMARY_FIELDS])
    with closing(_connect(path)) as conn:
        return pd.read_sql_query(
            "SELECT id, created_at, model_version, "
            + ", ".join(SUMMARY_FIELDS)
            + " FROM batch_summaries ORDER BY id DESC LIMIT ?",
            conn,
            params=(limit,),
        )
