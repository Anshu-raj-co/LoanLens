"""Cleaning for the primary dataset (``loan_approval_dataset.csv``).

Every function is pure: it returns a new DataFrame and never mutates its input.
Raw files in ``data/raw/`` are only ever read, never written.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = PROJECT_ROOT / "data" / "raw" / "loan_approval_dataset.csv"
PROCESSED_PATH = PROJECT_ROOT / "data" / "processed" / "loan_approval_clean.csv"
POLICY_PATH = PROJECT_ROOT / "config" / "policies" / "personal.yaml"  # default profile

TARGET = "loan_status"
ID_COLUMN = "loan_id"
TARGET_MAP: dict[str, int] = {"approved": 1, "rejected": 0}
ASSET_COLUMNS: tuple[str, ...] = (
    "residential_assets_value",
    "commercial_assets_value",
    "luxury_assets_value",
    "bank_asset_value",
)
NegativeStrategy = Literal["clip_zero", "drop", "nan"]
VALID_STRATEGIES: tuple[str, ...] = ("clip_zero", "drop", "nan")


def normalise_column_name(name: str) -> str:
    """Return a snake_case column name.

    Strips surrounding whitespace, lower-cases, drops a trailing unit in brackets
    (e.g. ``"loan_term (years)"`` -> ``"loan_term"``) and collapses any run of
    non-alphanumeric characters into a single underscore.
    """
    cleaned = re.sub(r"\(.*?\)", "", str(name)).strip().lower()
    cleaned = re.sub(r"[^0-9a-z]+", "_", cleaned)
    return cleaned.strip("_")


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with normalised column names.

    Raises:
        ValueError: if two columns collapse to the same normalised name.
    """
    new_names = [normalise_column_name(c) for c in df.columns]
    duplicates = sorted({n for n in new_names if new_names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Columns collide after normalisation: {duplicates}")
    out = df.copy()
    out.columns = new_names
    return out


def strip_string_values(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with leading/trailing whitespace removed from text cells."""
    out = df.copy()
    for col in out.select_dtypes(include=["object", "string"]).columns:
        out[col] = out[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return out


def map_target(df: pd.DataFrame, column: str = TARGET) -> pd.DataFrame:
    """Map ``loan_status`` text (Approved / Rejected, any case) to 1 / 0.

    Raises:
        KeyError: if the target column is missing.
        ValueError: if any value is not Approved or Rejected.
    """
    if column not in df.columns:
        raise KeyError(f"Target column '{column}' not found")
    out = df.copy()
    lowered = out[column].astype(str).str.strip().str.lower()
    unknown = sorted(set(lowered) - set(TARGET_MAP))
    if unknown:
        raise ValueError(f"Unexpected values in '{column}': {unknown}")
    out[column] = lowered.map(TARGET_MAP).astype("int64")
    return out


def count_negative_assets(df: pd.DataFrame, columns: tuple[str, ...] = ASSET_COLUMNS) -> int:
    """Return the number of rows with at least one negative asset value."""
    present = [c for c in columns if c in df.columns]
    if not present:
        return 0
    return int((df[present] < 0).any(axis=1).sum())


def handle_negative_assets(
    df: pd.DataFrame,
    strategy: NegativeStrategy = "clip_zero",
    columns: tuple[str, ...] = ASSET_COLUMNS,
) -> pd.DataFrame:
    """Treat negative asset values, which are data errors (assets cannot be negative).

    Args:
        df: input frame.
        strategy: ``"clip_zero"`` sets negatives to 0, ``"drop"`` removes the rows,
            ``"nan"`` sets negatives to missing.
        columns: asset columns to check (missing ones are ignored).

    Raises:
        ValueError: on an unknown strategy.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Use one of {VALID_STRATEGIES}")
    out = df.copy()
    present = [c for c in columns if c in out.columns]
    if not present:
        return out
    if strategy == "drop":
        mask = (out[present] < 0).any(axis=1)
        return out.loc[~mask].reset_index(drop=True)
    for col in present:
        neg = out[col] < 0
        if strategy == "clip_zero":
            out.loc[neg, col] = 0
        else:
            out[col] = out[col].astype("float64")
            out.loc[neg, col] = float("nan")
    return out


def drop_identifier(df: pd.DataFrame, column: str = ID_COLUMN) -> pd.DataFrame:
    """Return a copy of ``df`` without the identifier column (it carries no signal)."""
    return df.drop(columns=[column], errors="ignore")


def drop_duplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` without exact duplicate rows."""
    return df.drop_duplicates().reset_index(drop=True)


def load_negative_strategy(policy_path: Path = POLICY_PATH) -> NegativeStrategy:
    """Read ``cleaning.negative_assets_strategy`` from the policy file (default ``clip_zero``)."""
    with open(policy_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    strategy = (config.get("cleaning") or {}).get("negative_assets_strategy", "clip_zero")
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Invalid negative_assets_strategy '{strategy}' in {policy_path}")
    return strategy


def clean(df: pd.DataFrame, negative_strategy: NegativeStrategy = "clip_zero") -> pd.DataFrame:
    """Run the full cleaning pipeline on the raw primary dataset.

    Order: normalise columns, strip text, map target, treat negative assets,
    drop the identifier, then drop exact duplicates.
    """
    out = normalise_columns(df)
    out = strip_string_values(out)
    out = map_target(out)
    out = handle_negative_assets(out, negative_strategy)
    out = drop_identifier(out)
    return drop_duplicate_rows(out)


def build_clean_dataset(
    raw_path: Path = RAW_PATH,
    out_path: Path = PROCESSED_PATH,
    policy_path: Path = POLICY_PATH,
) -> pd.DataFrame:
    """Read the raw CSV, clean it with the configured strategy and write the processed CSV."""
    raw = pd.read_csv(raw_path)
    cleaned = clean(raw, load_negative_strategy(policy_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(out_path, index=False)
    return cleaned


if __name__ == "__main__":
    result = build_clean_dataset()
    print(f"Wrote {len(result):,} rows x {result.shape[1]} columns to {PROCESSED_PATH}")
