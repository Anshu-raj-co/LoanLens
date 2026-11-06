"""Storage of **anonymised** Bulk Check summaries (SQLAlchemy; SQLite or PostgreSQL).

By default only aggregate counts are stored: no names, no applicant IDs and no input
values. Per-row applicant IDs and statuses are stored only if
``storage.store_applicant_ids`` is set to ``true`` in the policy file.
Customer mode never writes here.

Where the data goes:

* ``path`` given: that SQLite file (tests and tools).
* else ``DATABASE_URL`` set: that database (SQLite or PostgreSQL).
* else the SQLite file from ``storage.db_path`` in the policy (``data/loanlens.sqlite``).

Database problems raise :class:`loanlens.db.DatabaseError` with a plain message.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import insert, select

from loanlens.config import PROJECT_ROOT, Policy, load_policy
from loanlens.db import engine as db_engine
from loanlens.db.engine import DatabaseError, session_scope
from loanlens.db.models import BatchSummary, batch_rows

__all__ = [
    "SUMMARY_FIELDS",
    "DatabaseError",
    "db_path",
    "latest_summary",
    "list_summaries",
    "resolve_url",
    "save_summary",
]

SUMMARY_FIELDS = (
    "total_rows",
    "valid_rows",
    "invalid_rows",
    "approved",
    "rejected",
    "borderline",
    "approval_rate",
)
_COLUMNS = ("id", "created_at", "model_version", *SUMMARY_FIELDS)


def db_path(policy: Policy | None = None) -> Path:
    """SQLite file from ``storage.db_path`` (relative paths are under the project root)."""
    policy = policy or load_policy()
    path = Path(policy.storage.db_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_url(path: Path | None = None, policy: Policy | None = None) -> str:
    """The database URL to use (see the module docstring for the order)."""
    if path is not None:
        return db_engine.sqlite_url(Path(path))
    if os.environ.get(db_engine.ENV_VAR):
        return db_engine.database_url()
    return db_engine.sqlite_url(db_path(policy))


def _exists(url: str) -> bool:
    """False only for a SQLite file that has not been created yet (nothing stored)."""
    file = db_engine.sqlite_file(url)
    return file is None or file.exists()


def save_summary(
    summary: dict[str, Any],
    model_version: str,
    results: pd.DataFrame | Iterable[pd.DataFrame] | None = None,
    policy: Policy | None = None,
    path: Path | None = None,
) -> int:
    """Store one batch summary and return its id.

    Args:
        summary: output of :func:`loanlens.batch.summarise` (aggregates only).
        model_version: version string of the model used.
        results: per-row results (one frame, or an iterable of frames so a large batch is
            never held in memory at once); used only when ``store_applicant_ids`` is enabled.
        policy: policy (for the storage settings); defaults to the personal profile.
        path: SQLite file to use instead of the configured database.

    Raises:
        DatabaseError: the database could not be reached (plain-English message).
    """
    policy = policy or load_policy()
    url = resolve_url(path, policy)
    rate = summary.get("approval_rate")
    rate = None if rate is None or rate != rate else float(rate)  # NaN -> NULL
    record = BatchSummary(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model_version=model_version,
        total_rows=int(summary["total_rows"]),
        valid_rows=int(summary["valid_rows"]),
        invalid_rows=int(summary["invalid_rows"]),
        approved=int(summary["approved"]),
        rejected=int(summary["rejected"]),
        borderline=int(summary["borderline"]),
        approval_rate=rate,
        likelihood_bands=json.dumps(summary.get("likelihood_bands", {})),
        top_rejection_reasons=json.dumps(summary.get("top_rejection_reasons", [])),
    )
    with session_scope(url) as session:
        session.add(record)
        session.flush()
        batch_id = int(record.id)
        if policy.storage.store_applicant_ids and results is not None:
            frames = [results] if isinstance(results, pd.DataFrame) else results
            for frame in frames:
                if not len(frame):
                    continue
                session.execute(
                    insert(batch_rows),
                    [
                        {
                            "batch_id": batch_id,
                            "applicant_id": str(a),
                            "status": str(s),
                            "probability": float(p),
                        }
                        for a, s, p in zip(
                            frame["applicant_id"],
                            frame["status"],
                            frame["probability"],
                            strict=True,
                        )
                    ],
                )
    return batch_id


def _to_dict(row: BatchSummary) -> dict[str, Any]:
    out = {c: getattr(row, c) for c in _COLUMNS}
    out["likelihood_bands"] = json.loads(row.likelihood_bands)
    out["top_rejection_reasons"] = json.loads(row.top_rejection_reasons)
    return out


def latest_summary(path: Path | None = None, url: str | None = None) -> dict[str, Any] | None:
    """The most recent batch summary, or ``None`` if no batch has been stored."""
    url = url or resolve_url(path)
    if not _exists(url):
        return None
    with session_scope(url) as session:
        row = session.scalars(select(BatchSummary).order_by(BatchSummary.id.desc()).limit(1))
        first = row.first()
        return _to_dict(first) if first is not None else None


def list_summaries(
    limit: int = 20, path: Path | None = None, url: str | None = None
) -> pd.DataFrame:
    """Recent batch summaries (newest first) as a table."""
    url = url or resolve_url(path)
    if not _exists(url):
        return pd.DataFrame(columns=["id", "created_at", *SUMMARY_FIELDS])
    stmt = (
        select(*(getattr(BatchSummary, c) for c in _COLUMNS))
        .order_by(BatchSummary.id.desc())
        .limit(int(limit))
    )
    with session_scope(url) as session:
        rows = session.execute(stmt).all()
    return pd.DataFrame([tuple(r) for r in rows], columns=list(_COLUMNS))
