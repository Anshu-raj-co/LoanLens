"""Shared fixtures."""

from __future__ import annotations

import secrets
from typing import Any

import pandas as pd
import pytest
from argon2 import PasswordHasher, Type

from loanlens import cleaning, jobs, model, storage, worker
from loanlens.auth import passwords
from loanlens.auth import service as auth_service
from loanlens.auth import settings as auth_settings
from loanlens.db import engine as db_engine

AUTH_ENV = (
    auth_settings.ENV_MODE,
    auth_settings.ENV_HOSTED,
    auth_settings.ENV_SESSION_MINUTES,
    auth_settings.ENV_LOCKOUT_ATTEMPTS,
    auth_settings.ENV_LOCKOUT_MINUTES,
    auth_settings.ENV_BOOTSTRAP_EMAIL,
    auth_settings.ENV_BOOTSTRAP_PASSWORD,
)
JOB_ENV = (
    jobs.ENV_RETENTION, jobs.ENV_CHUNK, jobs.ENV_MAX_ROWS, jobs.ENV_MAX_UPLOAD_MB,
    jobs.ENV_AUDIT, jobs.ENV_AUDIT_CHUNK, jobs.ENV_POLL, jobs.ENV_STALE,
)  # fmt: skip
# Generated per test run, never stored: the signing key for test sessions.
TEST_JWT_SECRET = secrets.token_urlsafe(48)
# Cheap argon2id parameters so the suite stays fast; production uses the library defaults.
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1, type=Type.ID)


@pytest.fixture(scope="session")
def clean_df() -> pd.DataFrame:
    """The processed primary dataset (skips if it has not been built)."""
    if not cleaning.PROCESSED_PATH.exists():
        pytest.skip("processed data not available; run `python -m loanlens.cleaning`")
    return pd.read_csv(cleaning.PROCESSED_PATH)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Tests never use a developer's database, settings or pinned model version.

    Every test gets its own empty SQLite database (``storage.db_path`` is redirected, so
    accounts and batch summaries both go there), a generated signing key and a fast hasher.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOANLENS_MODEL_VERSION", raising=False)
    for name in AUTH_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(auth_settings.ENV_SECRET, TEST_JWT_SECRET)
    for name in JOB_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(jobs.ENV_JOBS_DIR, str(tmp_path / "jobs"))
    monkeypatch.setenv(jobs.ENV_EMBEDDED, "0")  # tests run jobs explicitly
    monkeypatch.setattr(storage, "db_path", lambda policy=None: tmp_path / "loanlens.sqlite")
    monkeypatch.setattr(passwords, "HASHER", FAST_HASHER)
    auth_service.reset_bootstrap_check()
    auth_settings.reset_ephemeral_key()
    yield
    worker.stop_embedded()
    db_engine.reset_caches()


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
