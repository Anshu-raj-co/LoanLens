"""Chunked, memory-safe Bulk Check pipeline (internal; jobs run it through the worker).

For each chunk of the uploaded file (CSV or Parquet, ``chunk_size`` rows at a time):

1. validate the rows (:func:`loanlens.batch.validate_rows`, same limits as customer mode);
2. score the valid rows with the shared decision core (:func:`loanlens.batch.score`, which
   calls :func:`loanlens.decision.decide_many`), so every applicant gets exactly the result
   the single-application path would give;
3. write the chunk's audit records in bulk inserts (when auditing is on), before any result
   of the chunk is written to a file;
4. append the results to a Parquet file and a CSV file, and the bad rows (with their
   original row numbers) to an errors CSV;
5. add the chunk to running summary counts and report progress.

Only one chunk and its results are in memory at a time; the summary keeps counts only.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from loanlens import audit, batch, explain
from loanlens.config import Policy

ERROR_COLUMNS = ["row", batch.ID_COLUMN, "problem"]


class Cancelled(Exception):
    """Raised by a progress callback to stop the run after the current chunk."""


@dataclass(frozen=True)
class AuditContext:
    """Where and as whom the batch's audit records are written."""

    url: str
    user_ref: str
    actor_role: str
    request_id: str
    batch_id: str
    chunk_size: int = audit.CHUNK_SIZE


@dataclass
class Progress:
    """Running counts for one file (no applicant data)."""

    total_rows: int = 0  # rows read so far (valid and invalid)
    valid_rows: int = 0
    invalid_rows: int = 0
    approved: int = 0
    rejected: int = 0
    borderline: int = 0
    audited: int = 0
    chunks: int = 0
    bands: Counter = field(default_factory=Counter)
    codes: Counter = field(default_factory=Counter)

    def add(self, results: pd.DataFrame, n_errors: int, n_rows: int) -> None:
        """Add one scored chunk."""
        approved = int((results["status"] == "Approved").sum())
        self.total_rows += n_rows
        self.valid_rows += len(results)
        self.invalid_rows += n_errors
        self.approved += approved
        self.rejected += len(results) - approved
        self.borderline += int(results["borderline"].sum())
        self.chunks += 1
        if len(results):
            self.bands.update(results["likelihood"].str.split(" - ").str[-1])
            for joined in results.loc[results["status"] == "Rejected", "reason_codes"]:
                self.codes.update(c for c in joined.split(";") if c)

    def summary(self, top_n: int = 5) -> dict[str, Any]:
        """The same anonymised summary as :func:`loanlens.batch.summarise`."""
        valid = self.valid_rows
        return {
            "total_rows": self.total_rows,
            "valid_rows": valid,
            "invalid_rows": self.invalid_rows,
            "approved": self.approved,
            "rejected": self.rejected,
            "borderline": self.borderline,
            "approval_rate": self.approved / valid if valid else math.nan,
            "likelihood_bands": {k: int(v) for k, v in self.bands.most_common()},
            "top_rejection_reasons": [
                {"code": c, "reason": explain.REASON_LABELS.get(c, c), "count": int(k)}
                for c, k in self.codes.most_common(top_n)
            ],
        }


def result_schema(include_positive: bool = False) -> pa.Schema:
    """The fixed column types of the results file."""
    fields = [
        ("row", pa.int64()), (batch.ID_COLUMN, pa.string()), (batch.PRODUCT_COLUMN, pa.string()),
        ("status", pa.string()), ("probability", pa.float64()), ("likelihood", pa.string()),
        ("borderline", pa.bool_()), ("reasons", pa.string()), ("what_would_change", pa.string()),
        ("warnings", pa.string()), ("reason_codes", pa.string()),
    ]  # fmt: skip
    if include_positive:
        fields.append(("positive_factors", pa.string()))
    return pa.schema(fields)


@dataclass(frozen=True)
class Outputs:
    """The three output files of a run."""

    results_parquet: Path
    results_csv: Path
    errors_csv: Path


def run_file(
    input_path: Path,
    outputs: Outputs,
    policy: Policy,
    artifact: dict[str, Any],
    *,
    chunk_size: int,
    include_positive: bool = False,
    audit_context: AuditContext | None = None,
    max_rows: int | None = None,
    on_chunk: Callable[[Progress], None] | None = None,
    fmt: str | None = None,
) -> Progress:
    """Stream ``input_path`` through validation, scoring, auditing and the output files.

    ``policy`` is the loan type for rows without a ``product`` value. ``audit_context`` None
    means no audit records are written (benchmarks only; see ``LOANLENS_BATCH_AUDIT``).
    ``on_chunk`` is called after every chunk and may raise :class:`Cancelled`.

    Raises:
        BatchError: the file cannot be read, has missing columns, too many rows, or no rows.
        DatabaseError: audit records could not be written.
        Cancelled: from ``on_chunk``.
    """
    reader = batch.ChunkReader(input_path, chunk_size, fmt)
    model_version = str(artifact.get("version", "unknown"))
    schema = result_schema(include_positive)
    columns = schema.names
    progress = Progress()
    policies: dict[str, Policy] = {policy.profile: policy}
    with (
        pq.ParquetWriter(outputs.results_parquet, schema) as parquet,
        open(outputs.results_csv, "w", encoding="utf-8-sig", newline="") as results_csv,
        open(outputs.errors_csv, "w", encoding="utf-8-sig", newline="") as errors_csv,
    ):
        pd.DataFrame(columns=columns).to_csv(results_csv, index=False)
        pd.DataFrame(columns=ERROR_COLUMNS).to_csv(errors_csv, index=False)
        for chunk in reader:
            if max_rows is not None and progress.total_rows + len(chunk.frame) > max_rows:
                raise batch.BatchError(
                    f"The file has more than {max_rows:,} rows, the most one job accepts. "
                    "Please split it into smaller files."
                )
            parsed = batch.validate_rows(chunk.frame, policy.profile, chunk.first_row)
            results = batch.score(parsed, policy, artifact, include_positive=include_positive)
            if audit_context is not None and len(results):
                rows = audit.batch_rows(
                    parsed.values, results, model_version=model_version,
                    request_id=audit_context.request_id, batch_id=audit_context.batch_id,
                    user_ref=audit_context.user_ref, actor_role=audit_context.actor_role,
                    policies=policies,
                )  # fmt: skip
                audit.write(audit_context.url, rows, chunk_size=audit_context.chunk_size)
                progress.audited += len(rows)
            results = results.reindex(columns=columns)
            parquet.write_table(pa.Table.from_pandas(results, schema=schema, preserve_index=False))
            results.to_csv(results_csv, index=False, header=False)
            batch.errors_frame(parsed.errors).to_csv(errors_csv, index=False, header=False)
            progress.add(results, len(parsed.errors), parsed.total_rows)
            if on_chunk is not None:
                on_chunk(progress)
    if progress.total_rows == 0:
        raise batch.BatchError("The file has a header row but no applicant rows.")
    return progress
