"""Hosted mode, production secret checks, project-root resolution and the database command."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from app_support import open_page

from loanlens import config, hosted, jobs
from loanlens.auth import settings as auth_settings
from loanlens.auth.settings import ConfigurationError
from loanlens.db import __main__ as db_cli

STRONG = "Tst-" + secrets.token_urlsafe(24)  # generated per run, never stored


# ---- Secrets from Streamlit -------------------------------------------------------------------


def test_apply_secrets_copies_only_loanlens_settings() -> None:
    environ: dict[str, str] = {"LOANLENS_ENV": "production"}
    applied = hosted.apply_secrets(
        {
            "DATABASE_URL": "postgresql://u:p@h/d",
            "LOANLENS_HOSTED": 1,
            "LOANLENS_ENV": "development",  # already set: the environment wins
            "OTHER": "ignored",
            "LOANLENS_NESTED": {"a": 1},  # not a plain value
        },
        environ,
    )
    assert applied == ["DATABASE_URL", "LOANLENS_HOSTED"]
    assert environ == {
        "LOANLENS_ENV": "production",
        "DATABASE_URL": "postgresql://u:p@h/d",
        "LOANLENS_HOSTED": "1",
    }


# ---- Weak or missing secrets ---------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "change-me-change-me-change-me-change-me",
        "my-jwt-secret-value-for-the-loanlens-app",
        "abababababababababababababababababababab",
        "a" * 40,
    ],
)
def test_weak_secret_refused_in_hosted_mode(secret: str) -> None:
    assert auth_settings.weak_secret(secret)
    with pytest.raises(ConfigurationError, match="placeholder or has too little variety"):
        auth_settings.signing_key({"LOANLENS_HOSTED": "1", "LOANLENS_JWT_SECRET": secret})


def test_weak_secret_allowed_in_local_development() -> None:
    key = auth_settings.signing_key({"LOANLENS_JWT_SECRET": "a" * 40})
    assert not key.ephemeral


def test_strong_secret_accepted_in_hosted_mode() -> None:
    generated = secrets.token_urlsafe(48)
    assert not auth_settings.weak_secret(generated)
    key = auth_settings.signing_key({"LOANLENS_HOSTED": "1", "LOANLENS_JWT_SECRET": generated})
    assert key.value == generated


def test_missing_secret_refused_in_hosted_mode() -> None:
    with pytest.raises(ConfigurationError, match="is not set"):
        auth_settings.signing_key({"LOANLENS_HOSTED": "1"})


def test_bootstrap_checks_in_hosted_mode() -> None:
    base = {"LOANLENS_HOSTED": "1", "DATABASE_URL": "postgresql://u:p@h/d"}
    with pytest.raises(ConfigurationError, match="Only one of"):
        hosted.check_settings({**base, "LOANLENS_BOOTSTRAP_MANAGER_EMAIL": "m@example.com"})
    with pytest.raises(ConfigurationError, match="too weak"):
        hosted.check_settings(
            {**base, "LOANLENS_BOOTSTRAP_MANAGER_EMAIL": "m@example.com",
             "LOANLENS_BOOTSTRAP_MANAGER_PASSWORD": "password"}
        )  # fmt: skip
    ok = {**base, "LOANLENS_BOOTSTRAP_MANAGER_EMAIL": "m@example.com",
          "LOANLENS_BOOTSTRAP_MANAGER_PASSWORD": STRONG}  # fmt: skip
    assert hosted.check_settings(ok) == []


def test_bootstrap_not_checked_locally() -> None:
    assert hosted.check_settings({"LOANLENS_BOOTSTRAP_MANAGER_PASSWORD": "short"}) == []


@pytest.mark.parametrize("url", ["", "sqlite:///data/loanlens.sqlite"])
def test_hosted_without_postgresql_warns(url: str) -> None:
    warnings = hosted.check_settings({"LOANLENS_HOSTED": "1", "DATABASE_URL": url})
    assert warnings == [hosted.EPHEMERAL_DATABASE_WARNING]


def test_production_without_hosting_does_not_warn_about_sqlite() -> None:
    assert hosted.check_settings({"LOANLENS_ENV": "production"}) == []


# ---- Hosted job settings ----------------------------------------------------------------------


def test_hosted_job_defaults() -> None:
    settings = jobs.load_job_settings({"LOANLENS_HOSTED": "1"})
    assert settings.chunk_size == hosted.HOSTED_CHUNK_SIZE == 5_000
    assert settings.max_rows == hosted.HOSTED_MAX_ROWS
    assert settings.max_upload_mb == hosted.HOSTED_MAX_UPLOAD_MB
    assert settings.jobs_dir == hosted.HOSTED_JOBS_DIR
    assert settings.audit == "row"


def test_hosted_job_settings_can_be_overridden(tmp_path: Path) -> None:
    settings = jobs.load_job_settings(
        {"LOANLENS_HOSTED": "1", "LOANLENS_JOB_CHUNK_SIZE": "2000",
         "LOANLENS_JOB_MAX_ROWS": "50000", "LOANLENS_JOBS_DIR": str(tmp_path)}
    )  # fmt: skip
    assert (settings.chunk_size, settings.max_rows) == (2_000, 50_000)
    assert settings.jobs_dir == tmp_path


def test_local_job_defaults_unchanged() -> None:
    settings = jobs.load_job_settings({})
    assert (settings.chunk_size, settings.max_rows, settings.max_upload_mb) == (
        20_000, 1_000_000, 200,
    )  # fmt: skip


# ---- Pages in hosted mode ----------------------------------------------------------------------


def test_bulk_check_page_in_hosted_mode(app_path, artifact, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOANLENS_HOSTED", "1")
    monkeypatch.setenv(jobs.ENV_JOBS_DIR, str(tmp_path / "jobs"))
    at = open_page("pages/2_Bulk_Check.py").run()
    assert not at.exception
    texts = " ".join(str(w.value) for w in at.warning) + " ".join(str(m.value) for m in at.markdown)
    assert "synthetic or test data" in texts
    assert f"{hosted.HOSTED_MAX_ROWS:,} rows" in texts
    assert hosted.EPHEMERAL_DATABASE_WARNING in texts  # no external database here


def test_page_stops_on_weak_hosted_secret(app_path, monkeypatch) -> None:
    monkeypatch.setenv("LOANLENS_HOSTED", "1")
    monkeypatch.setenv("LOANLENS_JWT_SECRET", "change-me-change-me-change-me-change-me")
    at = open_page("Home.py", role=None).run()
    assert not at.exception
    assert any("LoanLens cannot start" in e.value for e in at.error)


# ---- Project root ----------------------------------------------------------------------------


def test_project_root_prefers_loanlens_home(tmp_path: Path) -> None:
    assert config.find_project_root({"LOANLENS_HOME": str(tmp_path)}) == tmp_path.resolve()


def test_project_root_from_source_checkout() -> None:
    root = config.find_project_root({})
    assert (root / "config" / "policies").is_dir() and root == config.PROJECT_ROOT


def test_project_root_falls_back_to_current_directory(tmp_path: Path) -> None:
    installed = tmp_path / "site-packages" / "loanlens" / "config.py"  # no config/ near it
    clone = tmp_path / "clone"
    (clone / "config" / "policies").mkdir(parents=True)
    assert config.find_project_root({}, source=installed, cwd=clone) == clone.resolve()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert config.find_project_root({}, source=installed, cwd=elsewhere) == (
        tmp_path.resolve()
    )  # the checkout guess: two levels above the package folder


# ---- python -m loanlens.db ----------------------------------------------------------------------


def test_db_command_upgrade_and_current(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.sqlite').as_posix()}")
    assert db_cli.main(["current"]) == 0
    assert "revision none" in capsys.readouterr().out
    assert db_cli.main(["upgrade"]) == 0
    out = capsys.readouterr().out
    assert "SQLite database at revision 0004_batch_jobs" in out and "cli.sqlite" not in out


def test_db_command_unreachable_database(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hidden-pw@127.0.0.1:1/none")
    assert db_cli.main(["upgrade"]) == 1
    err = capsys.readouterr().err
    assert "PostgreSQL" in err and "hidden-pw" not in err
