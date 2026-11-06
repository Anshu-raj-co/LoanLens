"""Database layer: engine, migrations and storage on SQLite (always) and PostgreSQL (optional).

PostgreSQL tests run only when ``LOANLENS_TEST_POSTGRES_URL`` points at a disposable test
database (its tables are dropped and recreated); otherwise they are skipped.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect, text

from loanlens import storage
from loanlens.config import load_policy
from loanlens.db import engine as db_engine
from loanlens.db.engine import DatabaseError, normalise_url

PG_ENV = "LOANLENS_TEST_POSTGRES_URL"
HEAD = "0004_batch_jobs"
REAL_DB_PATH = storage.db_path  # captured before the autouse fixture redirects it
SUMMARY = {
    "total_rows": 10,
    "valid_rows": 8,
    "invalid_rows": 2,
    "approved": 5,
    "rejected": 3,
    "borderline": 1,
    "approval_rate": 0.625,
    "likelihood_bands": {"Very likely": 4},
    "top_rejection_reasons": [{"code": "min_cibil", "reason": "CIBIL", "count": 2}],
}
RESULTS = pd.DataFrame(
    {"applicant_id": ["A1", "A2"], "status": ["Approved", "Rejected"], "probability": [0.9, 0.1]}
)


def _clean_postgres(url: str) -> None:
    db_engine.reset_caches()
    with db_engine.get_engine(url).begin() as conn:
        for table in (
            "batch_workers", "batch_jobs", "decision_audit", "auth_events", "users", "batch_rows",
            "batch_summaries",
            "alembic_version",
        ):  # fmt: skip
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    db_engine.reset_caches()


@pytest.fixture(params=["sqlite", "postgresql"])
def db_url(request, tmp_path) -> str:
    """A fresh, empty database URL for each backend."""
    if request.param == "sqlite":
        yield db_engine.sqlite_url(tmp_path / "test.sqlite")
        return
    url = os.environ.get(PG_ENV)
    if not url:
        pytest.skip(f"set {PG_ENV} to run the PostgreSQL tests")
    url = normalise_url(url)
    _clean_postgres(url)
    yield url
    _clean_postgres(url)


def test_migration_creates_tables(db_url) -> None:
    db_engine.ensure_schema(db_url)
    names = set(inspect(db_engine.get_engine(db_url)).get_table_names())
    assert {
        "batch_summaries",
        "batch_rows",
        "users",
        "auth_events",
        "decision_audit",
        "batch_jobs",
        "batch_workers",
        "alembic_version",
    } <= names
    with db_engine.get_engine(db_url).connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
    db_engine.ensure_schema(db_url)  # idempotent


def test_round_trip(db_url) -> None:
    assert storage.latest_summary(url=db_url) is None
    assert storage.list_summaries(url=db_url).empty
    policy = load_policy()
    enabled = policy.model_copy(
        update={"storage": policy.storage.model_copy(update={"store_applicant_ids": True})}
    )
    os.environ[db_engine.ENV_VAR] = db_url
    try:
        first = storage.save_summary(SUMMARY, "1.0.0", RESULTS, enabled)
        second = storage.save_summary({**SUMMARY, "approval_rate": float("nan")}, "1.0.0")
    finally:
        del os.environ[db_engine.ENV_VAR]
    assert second > first
    latest = storage.latest_summary(url=db_url)
    assert latest["id"] == second and latest["approval_rate"] is None  # NaN stored as NULL
    assert latest["likelihood_bands"] == {"Very likely": 4}
    assert latest["top_rejection_reasons"][0]["code"] == "min_cibil"
    table = storage.list_summaries(10, url=db_url)
    assert list(table.columns) == ["id", "created_at", "model_version", *storage.SUMMARY_FIELDS]
    assert list(table["id"]) == [second, first]  # newest first
    with db_engine.get_engine(db_url).connect() as conn:
        rows = conn.execute(text("SELECT batch_id, applicant_id FROM batch_rows")).all()
    assert sorted(r[1] for r in rows) == ["A1", "A2"] and {r[0] for r in rows} == {first}


def test_ids_not_stored_by_default(db_url) -> None:
    os.environ[db_engine.ENV_VAR] = db_url
    try:
        storage.save_summary(SUMMARY, "1.0.0", RESULTS, load_policy())
    finally:
        del os.environ[db_engine.ENV_VAR]
    with db_engine.get_engine(db_url).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM batch_rows")).scalar() == 0


def test_legacy_sqlite_database_is_upgraded(tmp_path) -> None:
    """A database created by the old sqlite3 code keeps its rows and gains Alembic tracking."""
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE batch_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT "
            "NOT NULL, model_version TEXT NOT NULL, total_rows INTEGER NOT NULL, valid_rows "
            "INTEGER NOT NULL, invalid_rows INTEGER NOT NULL, approved INTEGER NOT NULL, "
            "rejected INTEGER NOT NULL, borderline INTEGER NOT NULL, approval_rate REAL, "
            "likelihood_bands TEXT NOT NULL, top_rejection_reasons TEXT NOT NULL);"
            "CREATE TABLE batch_rows (batch_id INTEGER NOT NULL REFERENCES batch_summaries(id), "
            "applicant_id TEXT, status TEXT NOT NULL, probability REAL NOT NULL);"
            "INSERT INTO batch_summaries VALUES (1, '2026-01-01T00:00:00+00:00', '1.0.0', 3, 3, "
            "0, 2, 1, 0, 0.6667, '{}', '[]');"
        )
    assert storage.latest_summary(path)["id"] == 1
    assert storage.save_summary(SUMMARY, "1.0.0", path=path) == 2
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)


def test_resolve_url_order(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(db_engine.ENV_VAR, raising=False)
    monkeypatch.setattr(storage, "db_path", REAL_DB_PATH)
    assert storage.resolve_url().endswith("data/loanlens.sqlite")
    monkeypatch.setenv(db_engine.ENV_VAR, "sqlite:///other.sqlite")
    assert storage.resolve_url().endswith("/other.sqlite")
    assert Path(db_engine.sqlite_file(storage.resolve_url())).is_absolute()
    explicit = storage.resolve_url(tmp_path / "x.sqlite")  # an explicit file always wins
    assert explicit == db_engine.sqlite_url(tmp_path / "x.sqlite")


def test_default_url(monkeypatch) -> None:
    monkeypatch.delenv(db_engine.ENV_VAR, raising=False)
    assert db_engine.DEFAULT_URL == "sqlite:///data/loanlens.sqlite"
    assert db_engine.database_url().endswith("/data/loanlens.sqlite")


def test_postgres_urls_use_psycopg() -> None:
    assert normalise_url("postgresql://u:p@h:5432/d").startswith("postgresql+psycopg://")
    assert normalise_url("postgresql+psycopg2://u@h/d").startswith("postgresql+psycopg://")
    assert normalise_url("postgresql+psycopg://u@h/d") == "postgresql+psycopg://u@h/d"
    assert normalise_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_invalid_url_is_friendly() -> None:
    with pytest.raises(DatabaseError) as exc:
        normalise_url("not a url")
    assert "DATABASE_URL" in str(exc.value)


def test_unreachable_database_is_friendly() -> None:
    url = "postgresql://someone:hunter2-not-real@127.0.0.1:1/none"
    with pytest.raises(DatabaseError) as exc:
        storage.latest_summary(url=url)
    message = str(exc.value)
    assert "could not be reached" in message
    assert "hunter2" not in message and "127.0.0.1" not in message  # no URL or password
    assert exc.value.__cause__ is None  # driver error suppressed


def _logging_state() -> dict:
    """The parts of the logging configuration that alembic.ini's fileConfig would change."""
    root = logging.getLogger()
    loggers = {
        name: (lg.disabled, lg.level, list(lg.handlers), lg.propagate)
        for name, lg in logging.Logger.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    return {"root": (root.level, list(root.handlers)), "loggers": loggers}


@pytest.fixture
def restore_logging():
    """Put the logging configuration back after a test that runs Alembic's own setup."""
    root = logging.getLogger()
    before = _logging_state()
    yield
    level, handlers = before["root"]
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level)
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if not isinstance(lg, logging.Logger):
            continue
        if name in before["loggers"]:
            disabled, lvl, hdlrs, propagate = before["loggers"][name]
            lg.disabled, lg.level, lg.handlers, lg.propagate = disabled, lvl, hdlrs, propagate
        else:
            lg.disabled = False
    logging.Logger.manager._clear_cache()


APP_LOGGERS = ("loanlens.auth.settings", "loanlens.auth.service", "loanlens.api")


def test_ensure_schema_leaves_logging_alone(db_url) -> None:
    """Running migrations from code never disables loggers or replaces root handlers."""
    loggers = [logging.getLogger(name) for name in APP_LOGGERS]
    before = _logging_state()
    db_engine.reset_caches()
    db_engine.ensure_schema(db_url)
    assert db_url in db_engine._migrated  # the migrations really ran
    assert all(not lg.disabled for lg in loggers)
    after = _logging_state()
    assert after["root"] == before["root"]  # root level and handlers unchanged
    # every logger that existed before is unchanged (Alembic may add its own new loggers)
    assert {name: after["loggers"][name] for name in before["loggers"]} == before["loggers"]


def test_caplog_works_after_ensure_schema(db_url, caplog) -> None:
    """A loanlens warning emitted after migrations ran in the same test is still captured."""
    from loanlens import auth

    db_engine.reset_caches()
    db_engine.ensure_schema(db_url)
    with caplog.at_level(logging.WARNING):
        logging.getLogger("loanlens.auth.settings").warning("probe after migrations")
        assert not auth.bootstrap_from_env({auth.settings.ENV_BOOTSTRAP_EMAIL: "a@example.com"})
    assert "probe after migrations" in caplog.text
    assert "Only one of" in caplog.text


def test_alembic_command_line(tmp_path, monkeypatch, capsys, restore_logging) -> None:
    """`alembic upgrade head` from the project root uses DATABASE_URL; --sql works offline."""
    from alembic import command
    from alembic.config import Config

    from loanlens.config import PROJECT_ROOT

    loggers = [logging.getLogger(name) for name in APP_LOGGERS]
    db = tmp_path / "cli.sqlite"
    monkeypatch.setenv(db_engine.ENV_VAR, f"sqlite:///{db.as_posix()}")
    monkeypatch.chdir(PROJECT_ROOT)
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    assert all(not lg.disabled for lg in loggers)  # even the CLI setup keeps existing loggers
    with sqlite3.connect(db) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "batch_summaries",
        "batch_rows",
        "users",
        "auth_events",
        "decision_audit",
        "batch_jobs",
        "batch_workers",
        "alembic_version",
    } <= names
    command.downgrade(cfg, "base")
    with sqlite3.connect(db) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "batch_summaries" not in names and "users" not in names
    command.upgrade(cfg, "head", sql=True)  # offline mode prints the SQL instead
    sql = capsys.readouterr().out
    assert "CREATE TABLE batch_summaries" in sql and "CREATE TABLE users" in sql
    db_engine.reset_caches()


ORDER_SENSITIVE = (
    "tests/test_db.py::test_alembic_command_line",
    "tests/test_auth.py::test_missing_secret_in_development_uses_a_temporary_key",
    "tests/test_auth.py::test_bootstrap_creates_the_first_manager_once",
    "tests/test_auth.py::test_bootstrap_needs_both_values_and_a_valid_password",
)


@pytest.mark.parametrize("order", ["cli_first", "cli_last"])
def test_auth_logging_tests_pass_in_either_order(order) -> None:
    """The auth warnings are captured whether or not the Alembic CLI test ran before them."""
    from loanlens.config import PROJECT_ROOT

    ids = (
        list(ORDER_SENSITIVE)
        if order == "cli_first"
        else list(ORDER_SENSITIVE[1:]) + [ORDER_SENSITIVE[0]]
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", *ids],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    assert "4 passed" in result.stdout
    assert "Logging error" not in result.stdout + result.stderr
