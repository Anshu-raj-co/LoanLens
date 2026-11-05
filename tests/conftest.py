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


@pytest.fixture(scope="session")
def artifact(clean_df: pd.DataFrame) -> dict[str, Any]:
    """The saved model artifact; trains and saves it first if it is missing."""
    if not model.MODEL_PATH.exists():
        model.save_artifact(model.train_final(clean_df))
        model.load_artifact.cache_clear()
    return model.load_artifact()


APP_DIR = cleaning.PROJECT_ROOT / "app"


@pytest.fixture(scope="session")
def app_path() -> str:
    """Make ``app/`` importable (as ``streamlit run app/Home.py`` does) and return it."""
    import sys

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    return str(APP_DIR)
