"""Build the committed aggregates file that lets the app run without the data folder.

Usage (from the project root, with the cleaned training data present)::

    python scripts/build_hosted_assets.py           # write data/hosted/analytics_aggregates.json
    python scripts/build_hosted_assets.py --check   # exit 1 if the committed file is out of date

The file holds aggregates only: counts and approval rates per CIBIL band, loan term and
loan-size quintile, and the active model's feature-importance shares. No row of the
dataset is written. The registry and the active model artifact are committed separately
(see ``.gitignore``), so a fresh clone needs no training either.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from loanlens import analytics, cleaning, explain
from loanlens import model as model_mod


def build_content() -> dict:
    """Aggregates of the cleaned training data and the active model."""
    path = Path(cleaning.PROCESSED_PATH)
    if not path.exists():
        raise SystemExit(
            f"{path} was not found. Put the dataset in data/raw/ and run "
            "`python -m loanlens.cleaning` first."
        )
    df = pd.read_csv(path)
    artifact = model_mod.load_artifact()
    importance = explain.feature_importance(artifact, model_mod.build_frame(df))
    return analytics.build(df, importance, artifact, model_mod.data_hash(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="only compare with the committed file; exit 1 if it differs",
    )
    parser.add_argument("--out", type=Path, default=analytics.AGGREGATES_PATH)
    args = parser.parse_args(argv)
    content = build_content()
    if args.check:
        current = analytics.load(args.out)
        if current != content:
            print(f"{args.out} is out of date. Run python scripts/build_hosted_assets.py.")
            return 1
        print(f"{args.out} is up to date.")
        return 0
    out = analytics.write(content, args.out)
    print(f"Wrote {out} ({out.stat().st_size:,} bytes, aggregates of "
          f"{content['training_rows']:,} rows).")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
