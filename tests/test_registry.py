"""Model registry: round trip, activation, hash checks, legacy migration and the CLI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from loanlens import model as m
from loanlens import registry as reg
from loanlens.decision import decide
from loanlens.examples import EXAMPLES

REAL_REGISTRY = reg.REGISTRY_PATH  # captured before any test redirects it


@pytest.fixture
def active_file() -> Path:
    """The artifact the real registry marks as active (verified)."""
    _, path = reg.resolve_artifact(REAL_REGISTRY)
    return path


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch) -> Path:
    """An empty registry in a temporary folder, used as the default for this test."""
    path = tmp_path / "models" / "registry.json"
    path.parent.mkdir()
    monkeypatch.setattr(reg, "REGISTRY_PATH", path)
    monkeypatch.setattr(m, "LEGACY_MODEL_PATH", path.parent / "loanlens_model.joblib")
    m.load_artifact.cache_clear()
    yield path
    m.load_artifact.cache_clear()


def _copy_as(active_file: Path, registry_path: Path, version: str) -> tuple[Path, dict]:
    target = registry_path.parent / reg.artifact_filename(version)
    shutil.copyfile(active_file, target)
    meta = {"version": version, "features": ["cibil_score"], "n_train": 10, "cv_metrics": {}}
    return target, meta


# ---- The committed registry ----------------------------------------------------------------


def test_real_registry_has_one_active_verified_model(active_file) -> None:
    registry = reg.load_registry(REAL_REGISTRY)
    assert [e.status for e in registry.models].count("active") == 1
    entry = registry.get(registry.active)
    assert entry.version == "1.0.0" and entry.artifact == "loanlens_model_1.0.0.joblib"
    assert entry.features == list(m.FINAL_FEATURES)
    assert entry.cv_metrics["roc_auc"] == pytest.approx(0.9942)
    assert reg.file_sha256(active_file) == entry.artifact_sha256
    assert len(entry.training_data_hash) == 64


def test_registered_model_predictions_unchanged(artifact, active_file) -> None:
    """Loading through the registry gives the same model as loading the file directly."""
    direct = m.load_artifact(active_file)
    frame = m.build_frame(pd.DataFrame([e[1] for e in EXAMPLES]))
    np.testing.assert_array_equal(m.predict_proba(artifact, frame), m.predict_proba(direct, frame))
    assert artifact["version"] == "1.0.0"


# ---- Round trip and activation -------------------------------------------------------------


def test_round_trip(tmp_registry, active_file) -> None:
    assert reg.load_registry().models == []
    path, meta = _copy_as(active_file, tmp_registry, "1.0.0")
    entry = reg.register(path, meta, "a" * 64)
    assert entry.status == "active" and entry.artifact_bytes == path.stat().st_size
    again = reg.load_registry()
    assert again.active == "1.0.0" and again.get("1.0.0") == entry
    data = json.loads(tmp_registry.read_text(encoding="utf-8"))
    assert data["models"][0]["artifact_sha256"] == reg.file_sha256(path)
    assert m.load_artifact()["version"] == "1.0.0"  # the real artifact's own version field


def test_activation_switches_status(tmp_registry, active_file) -> None:
    for version in ("1.0.0", "1.1.0"):
        path, meta = _copy_as(active_file, tmp_registry, version)
        reg.register(path, meta, "b" * 64, activate=(version == "1.0.0"))
    registry = reg.load_registry()
    assert registry.active == "1.0.0"
    assert {e.version: e.status for e in registry.models} == {
        "1.0.0": "active",
        "1.1.0": "archived",
    }
    reg.activate("1.1.0")
    registry = reg.load_registry()
    assert registry.active == "1.1.0"
    assert [e.status for e in registry.models] == ["archived", "active"]
    assert reg.next_version(registry) == "1.2.0"
    with pytest.raises(reg.RegistryError, match="not registered"):
        reg.activate("9.9.9")


def test_duplicate_version_rejected(tmp_registry, active_file) -> None:
    path, meta = _copy_as(active_file, tmp_registry, "1.0.0")
    reg.register(path, meta, "c" * 64)
    with pytest.raises(reg.RegistryError, match="already registered"):
        reg.register(path, meta, "c" * 64)


def test_environment_variable_selects_version(tmp_registry, active_file, monkeypatch) -> None:
    for version in ("1.0.0", "2.0.0"):
        path, meta = _copy_as(active_file, tmp_registry, version)
        reg.register(path, meta, "d" * 64)
    monkeypatch.setenv(reg.ENV_VERSION, "1.0.0")
    entry, path = reg.resolve_artifact()
    assert entry.version == "1.0.0" and path.name == "loanlens_model_1.0.0.joblib"
    monkeypatch.setenv(reg.ENV_VERSION, "3.0.0")
    with pytest.raises(reg.RegistryError, match="3.0.0 is not registered"):
        reg.resolve_artifact()


# ---- Integrity -----------------------------------------------------------------------------


def test_hash_mismatch_is_detected(tmp_registry, active_file) -> None:
    path, meta = _copy_as(active_file, tmp_registry, "1.0.0")
    reg.register(path, meta, "e" * 64)
    with open(path, "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(reg.ArtifactIntegrityError, match="does not match the fingerprint"):
        m.load_artifact()
    with pytest.raises(reg.ArtifactIntegrityError):
        reg.activate("1.0.0")


def test_missing_artifact_and_empty_registry(tmp_registry, active_file) -> None:
    with pytest.raises(FileNotFoundError, match="python -m loanlens.model"):
        m.load_artifact()
    path, meta = _copy_as(active_file, tmp_registry, "1.0.0")
    reg.register(path, meta, "f" * 64)
    path.unlink()
    with pytest.raises(FileNotFoundError, match="is missing"):
        m.load_artifact()


def test_invalid_registry_file(tmp_registry) -> None:
    tmp_registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(reg.RegistryError, match="not valid"):
        reg.load_registry()


def test_version_names_are_checked() -> None:
    assert reg.artifact_filename("1.2.3") == "loanlens_model_1.2.3.joblib"
    for bad in ("1.2", "../1.0.0", "v1.0.0"):
        with pytest.raises(reg.RegistryError):
            reg.artifact_filename(bad)
    assert reg.next_version(reg.Registry()) == "1.0.0"


# ---- Legacy migration ----------------------------------------------------------------------


def test_legacy_artifact_is_migrated_unchanged(tmp_registry, active_file) -> None:
    legacy = tmp_registry.parent / "loanlens_model.joblib"
    shutil.copyfile(active_file, legacy)
    legacy.with_suffix(".json").write_text("{}", encoding="utf-8")
    before = reg.file_sha256(legacy)
    entry = m.migrate_legacy_artifact()
    assert entry is not None and entry.status == "active" and entry.version == "1.0.0"
    target = tmp_registry.parent / "loanlens_model_1.0.0.joblib"
    assert not legacy.exists() and target.exists() and target.with_suffix(".json").exists()
    assert reg.file_sha256(target) == before == entry.artifact_sha256
    assert "pre-registry" in entry.notes
    assert m.migrate_legacy_artifact() is None  # only once


# ---- Training and the CLI ------------------------------------------------------------------


def test_train_and_register_keeps_older_versions(tmp_registry, clean_df) -> None:
    sample = clean_df.sample(600, random_state=3)
    first = m.train_and_register(sample, cv_metrics={"roc_auc": 0.5})
    second = m.train_and_register(sample, activate=False)
    assert (first.version, second.version) == ("1.0.0", "1.1.0")
    registry = reg.load_registry()
    assert registry.active == "1.0.0" and second.status == "archived"
    assert len(first.training_data_hash) == 64 and first.cv_metrics == {"roc_auc": 0.5}
    for version in ("1.0.0", "1.1.0"):
        assert (tmp_registry.parent / f"loanlens_model_{version}.joblib").exists()
    assert m.load_artifact()["version"] == "1.0.0"
    with pytest.raises(reg.RegistryError, match="already exists"):
        m.train_and_register(sample, version="1.1.0")


def test_cli_list_and_activate(tmp_registry, active_file, capsys) -> None:
    assert m.cli(["--list"]) == 0
    assert "No models are registered" in capsys.readouterr().out
    for version in ("1.0.0", "1.1.0"):
        path, meta = _copy_as(active_file, tmp_registry, version)
        reg.register(path, meta, "0" * 64, activate=False)
    assert m.cli(["--list"]) == 0
    out = capsys.readouterr().out
    assert "1.0.0" in out and "1.1.0" in out and "active" in out and "archived" in out
    assert m.cli(["--activate", "1.1.0"]) == 0
    assert "1.1.0 is now active" in capsys.readouterr().out
    assert reg.load_registry().active == "1.1.0"
    assert m.cli(["--activate", "4.0.0"]) == 1
    assert "Error: Model version 4.0.0 is not registered" in capsys.readouterr().out


def test_decisions_carry_the_model_version(artifact) -> None:
    assert decide(EXAMPLES[0][1]).model_version == reg.load_registry(REAL_REGISTRY).active
