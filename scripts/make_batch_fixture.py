"""Generate the fully synthetic 1,000-row Bulk Check test file ``tests/fixtures/batch_1000.csv``.

Every value is drawn from a seeded random generator, so no row comes from any real or
public dataset. Values are plausible (CIBIL 300-900, even loan terms of 2-20 years, loans of
1.5x to 4x annual income, assets scaled to income), and about 5% of incomes and loan amounts
are written with Indian digit grouping (for example "12,50,000") to exercise that parser.

Twenty rows at fixed positions are deliberately invalid (blank, non-numeric, decimal,
out-of-range, zero, negative and infinite values). ``tests/test_batch.py`` checks that exactly
those rows are reported and skipped. Run with:
    python scripts/make_batch_fixture.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from loanlens.formatting import group_indian

SEED = 20261106
N_ROWS = 1000
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "batch_1000.csv"

COLUMNS = [
    "applicant_id",
    "cibil_score",
    "income_annum",
    "loan_amount",
    "loan_term",
    "residential_assets_value",
    "commercial_assets_value",
    "luxury_assets_value",
    "bank_asset_value",
]

# CSV line number (header is line 1) -> (column, bad value). Same positions and error types
# as the earlier fixture, so the expectations in tests/test_batch.py are unchanged.
BAD_ROWS: dict[int, tuple[str, str]] = {
    150: ("cibil_score", "1000"),
    153: ("loan_amount", "twelve lakh"),
    168: ("loan_term", "0"),
    230: ("loan_term", ""),
    238: ("bank_asset_value", "n/a"),
    249: ("income_annum", "1,00,000x"),
    324: ("cibil_score", "abc"),
    334: ("income_annum", "-50000"),
    335: ("residential_assets_value", "-100000"),
    366: ("luxury_assets_value", "-1"),
    370: ("loan_amount", "0"),
    432: ("commercial_assets_value", ""),
    499: ("cibil_score", "650.5"),
    546: ("loan_term", "7.5"),
    575: ("loan_term", "45"),
    628: ("cibil_score", "250"),
    678: ("cibil_score", ""),
    784: ("loan_amount", "inf"),
    829: ("income_annum", "0"),
    932: ("income_annum", ""),
}


def _round_lakh(values: np.ndarray) -> np.ndarray:
    """Round to the nearest 1,00,000 (INR), as in typical application amounts."""
    return (np.round(values / 100_000) * 100_000).astype(np.int64)


def build(seed: int = SEED, n_rows: int = N_ROWS) -> pd.DataFrame:
    """Return the synthetic fixture as a frame of strings (exactly as written to CSV)."""
    rng = np.random.default_rng(seed)
    cibil = rng.integers(300, 901, n_rows)
    income = _round_lakh(rng.uniform(200_000, 9_900_000, n_rows))
    loan = _round_lakh(income * rng.uniform(1.5, 4.0, n_rows))
    term = rng.choice(np.arange(2, 21, 2), n_rows)
    residential = _round_lakh(income * rng.uniform(0.0, 4.0, n_rows))
    commercial = _round_lakh(income * rng.uniform(0.0, 2.5, n_rows))
    luxury = _round_lakh(income * rng.uniform(0.5, 4.0, n_rows))
    bank = _round_lakh(income * rng.uniform(0.2, 1.5, n_rows))

    frame = pd.DataFrame(
        {
            "applicant_id": [f"APP-{i:05d}" for i in range(1, n_rows + 1)],
            "cibil_score": cibil,
            "income_annum": income,
            "loan_amount": loan,
            "loan_term": term,
            "residential_assets_value": residential,
            "commercial_assets_value": commercial,
            "luxury_assets_value": luxury,
            "bank_asset_value": bank,
        }
    ).astype(str)

    for col in ("income_annum", "loan_amount"):
        grouped = rng.random(n_rows) < 0.05
        frame.loc[grouped, col] = [group_indian(float(v)) for v in frame.loc[grouped, col]]

    for line, (col, value) in BAD_ROWS.items():
        frame.loc[line - 2, col] = value
    return frame[COLUMNS]


def main() -> None:
    """Write the fixture and print a one-line summary."""
    frame = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT, index=False)
    print(f"Wrote {len(frame):,} rows ({len(BAD_ROWS)} deliberately bad) to {OUT}")


if __name__ == "__main__":
    main()
