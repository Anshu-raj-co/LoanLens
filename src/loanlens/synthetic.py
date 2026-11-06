"""Fully synthetic applicants for benchmarks and large-file tests (vectorised, seeded).

Values are drawn at random within the ranges the active model saw in training (the
``training_ranges`` stored in the model artifact, so no data folder is needed): CIBIL 300 to
900, even loan terms of 2 to 20 years, loans of 1.5 to 4 times annual income, and assets
scaled to income and clipped to the training ranges. No row comes from any real or public
dataset; every ``applicant_id`` starts with ``SYN-`` to mark it as synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from loanlens.batch import ID_COLUMN, REQUIRED_COLUMNS

DEFAULT_RANGES: dict[str, tuple[float, float]] = {
    "income_annum": (200_000.0, 9_900_000.0),
    "loan_amount": (300_000.0, 39_500_000.0),
    "loan_term": (2.0, 20.0),
    "cibil_score": (300.0, 900.0),
    "residential_assets_value": (0.0, 29_100_000.0),
    "commercial_assets_value": (0.0, 19_400_000.0),
    "luxury_assets_value": (300_000.0, 39_200_000.0),
    "bank_asset_value": (0.0, 14_700_000.0),
    "loan_to_income": (1.5, 4.0),
}
# Asset value as a multiple of annual income: (low, high) of a uniform draw.
ASSET_FACTORS = {
    "residential_assets_value": (0.0, 3.0),
    "commercial_assets_value": (0.0, 2.0),
    "luxury_assets_value": (0.5, 3.5),
    "bank_asset_value": (0.0, 1.4),
}
STEP = 100_000  # amounts are whole lakhs, like the training data


def _lakhs(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip(np.round(values / STEP) * STEP, lo, hi).astype("int64")


def generate(
    n: int, seed: int = 20261106, ranges: Mapping[str, tuple[float, float]] | None = None
) -> pd.DataFrame:
    """``n`` synthetic applicants with an ID column and the eight input columns."""
    r = {**DEFAULT_RANGES, **(ranges or {})}
    rng = np.random.default_rng(seed)
    inc_lo, inc_hi = r["income_annum"]
    income = _lakhs(rng.uniform(inc_lo, inc_hi, n), inc_lo, inc_hi)
    lti = rng.uniform(*r["loan_to_income"], n)
    frame = pd.DataFrame(
        {
            ID_COLUMN: np.char.add("SYN-", np.char.zfill(np.arange(1, n + 1).astype(str), 7)),
            "cibil_score": rng.integers(int(r["cibil_score"][0]), int(r["cibil_score"][1]) + 1, n),
            "income_annum": income,
            "loan_amount": _lakhs(income * lti, *r["loan_amount"]),
            "loan_term": rng.integers(1, 11, n) * 2,
        }
    )
    for name, (lo_f, hi_f) in ASSET_FACTORS.items():
        frame[name] = _lakhs(income * rng.uniform(lo_f, hi_f, n), *r[name])
    return frame[[ID_COLUMN, *REQUIRED_COLUMNS]]


def write_csv(path: Path, n: int, seed: int = 20261106, block: int = 100_000,
              ranges: Mapping[str, tuple[float, float]] | None = None) -> Path:  # fmt: skip
    """Write ``n`` synthetic rows to a CSV file in blocks (bounded memory)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for i, start in enumerate(range(0, n, block)):
            part = generate(min(block, n - start), seed + i, ranges)
            part[ID_COLUMN] = np.char.add(
                "SYN-", np.char.zfill(np.arange(start + 1, start + len(part) + 1).astype(str), 7)
            )
            part.to_csv(fh, index=False, header=i == 0)
    return path
