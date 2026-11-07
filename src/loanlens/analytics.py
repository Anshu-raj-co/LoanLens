"""Aggregates behind the Analytics page, from the training data or from a committed file.

Locally, with the cleaned training data in ``data/processed/``, the tables are computed
from it as before. A fresh clone, a Docker image or a hosted copy has no data folder; it
uses ``data/hosted/analytics_aggregates.json`` instead, built by
``python scripts/build_hosted_assets.py``. That file holds aggregates only (counts and
approval rates per group, and the model's feature-importance shares), never a row of the
dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from loanlens.charts import approval_rate_table, quantile_bands
from loanlens.config import PROJECT_ROOT
from loanlens.features import cibil_band

AGGREGATES_PATH = PROJECT_ROOT / "data" / "hosted" / "analytics_aggregates.json"
FORMAT_VERSION = 1
LOAN_SIZE_BANDS = 5
TABLES = ("by_cibil_band", "by_loan_term", "by_loan_size")
TABLE_COLUMNS = ("applications", "approved", "approval_rate")
TRAINING_DATA, AGGREGATES = "training data", "aggregates file"


class AggregatesError(ValueError):
    """The aggregates file is missing a part or has an unexpected shape."""


@dataclass(frozen=True)
class AnalyticsData:
    """Approval tables for the Analytics charts and where they came from."""

    by_cibil_band: pd.DataFrame
    by_loan_term: pd.DataFrame
    by_loan_size: pd.DataFrame
    rows: int
    source: Literal["training data", "aggregates file"]


def approval_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The three approval-rate tables of the Analytics page from a cleaned frame."""
    return {
        "by_cibil_band": approval_rate_table(
            df, cibil_band(df["cibil_score"]).rename("cibil_band")
        ),
        "by_loan_term": approval_rate_table(df, "loan_term"),
        "by_loan_size": approval_rate_table(
            df, quantile_bands(df["loan_amount"], LOAN_SIZE_BANDS).rename("loan_amount")
        ),
    }


def from_frame(df: pd.DataFrame) -> AnalyticsData:
    """Analytics tables computed from the training data."""
    return AnalyticsData(**approval_tables(df), rows=len(df), source=TRAINING_DATA)


def _table_records(table: pd.DataFrame) -> dict[str, Any]:
    group = table.columns[0]
    labels = table[group].astype(str)  # by column, so whole numbers stay "2", not "2.0"
    return {
        "group": str(group),
        "rows": [
            {
                "group": label,
                "applications": int(apps),
                "approved": int(approved),
                "approval_rate": round(float(rate), 6),
            }
            for label, apps, approved, rate in zip(
                labels,
                table["applications"],
                table["approved"],
                table["approval_rate"],
                strict=True,
            )
        ],
    }


def build(
    df: pd.DataFrame, importance: pd.Series, artifact: dict[str, Any], data_hash: str
) -> dict[str, Any]:
    """The content of the aggregates file (deterministic: no timestamps).

    Args:
        df: the cleaned training data.
        importance: feature-importance shares of the active model on that data.
        artifact: the active model artifact (its version and training time are recorded so
            stale importance values are never shown for another model).
        data_hash: SHA-256 of the cleaned training data file.
    """
    tables = approval_tables(df)
    return {
        "format_version": FORMAT_VERSION,
        "description": (
            "Aggregates of the public synthetic training data for the Analytics page when "
            "the data folder is absent. Counts and approval rates per group and feature "
            "importance only; no row-level data. Built by scripts/build_hosted_assets.py."
        ),
        "training_rows": int(len(df)),
        "training_data_sha256": data_hash,
        "tables": {name: _table_records(tables[name]) for name in TABLES},
        "feature_importance": {
            "measure": "mean absolute SHAP share",
            "model_version": str(artifact.get("version")),
            "model_trained_at": str(artifact.get("trained_at")),
            "shares": {str(k): round(float(v), 6) for k, v in importance.items()},
        },
    }


def write(content: dict[str, Any], path: Path = AGGREGATES_PATH) -> Path:
    """Write the aggregates file (stable formatting so a rebuild gives the same bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return path


def load(path: Path = AGGREGATES_PATH) -> dict[str, Any] | None:
    """The aggregates file's content, or None when it does not exist.

    Raises:
        AggregatesError: the file exists but cannot be used.
    """
    if not path.exists():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AggregatesError("The analytics aggregates file could not be read.") from None
    if not isinstance(content, dict) or content.get("format_version") != FORMAT_VERSION:
        raise AggregatesError("The analytics aggregates file has an unknown format.")
    return content


def _table(record: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(record["rows"], columns=["group", *TABLE_COLUMNS])
    return frame.rename(columns={"group": record["group"]})


def from_aggregates(content: dict[str, Any]) -> AnalyticsData:
    """Analytics tables from the aggregates file's content."""
    try:
        tables = {name: _table(content["tables"][name]) for name in TABLES}
        rows = int(content["training_rows"])
    except (KeyError, TypeError, ValueError):
        raise AggregatesError("The analytics aggregates file is incomplete.") from None
    return AnalyticsData(**tables, rows=rows, source=AGGREGATES)


def importance_from_aggregates(
    content: dict[str, Any], artifact: dict[str, Any]
) -> pd.Series | None:
    """Stored feature-importance shares, only if they belong to the given model."""
    stored = content.get("feature_importance") or {}
    if stored.get("model_version") != str(artifact.get("version")) or stored.get(
        "model_trained_at"
    ) != str(artifact.get("trained_at")):
        return None
    shares = stored.get("shares") or {}
    if not shares:
        return None
    return pd.Series({str(k): float(v) for k, v in shares.items()}, dtype="float64")
