"""Shared fixtures."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from loanlens import cleaning, model


@pytest.fixture(scope="session")
def clean_df() -> pd.DataFrame:
    """The processed primary dataset (skips if it has not been built)."""
    if not cleaning.PROCESSED_PATH.exists():
        pytest.skip("processed data not available; run `python -m loanlens.cleaning`")
    return pd.read_csv(cleaning.PROCESSED_PATH)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never use a developer's database or pinned model version."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOANLENS_MODEL_VERSION", raising=False)


@pytest.fixture(scope="session")
def artifact(clean_df: pd.DataFrame) -> dict[str, Any]:
    """The active registered model; trains and registers one first if none exists."""
    try:
        return model.load_artifact()
    except FileNotFoundError:
        model.train_and_register(clean_df, model.data_hash(cleaning.PROCESSED_PATH))
        return model.load_artifact()


APP_DIR = cleaning.PROJECT_ROOT / "app"


@pytest.fixture(scope="session")
def app_path() -> str:
    """Make ``app/`` importable (as ``streamlit run app/Home.py`` does) and return it."""
    import sys

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    return str(APP_DIR)
