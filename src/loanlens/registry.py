"""Model registry: every trained model version, its fingerprints and which one is active.

``models/registry.json`` records, for each version: when it was created, a hash of the
training data, the feature list, cross-validation metrics, the artifact file name, the
artifact's SHA-256 and its status (``active`` or ``archived``). Exactly one version is
active. The loader uses the active version (or ``LOANLENS_MODEL_VERSION``) and refuses an
artifact whose bytes no longer match the recorded hash.

Older artifacts are kept, so any version can be re-activated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from loanlens.config import PROJECT_ROOT, SEMVER

MODEL_DIR = PROJECT_ROOT / "models"
REGISTRY_PATH = MODEL_DIR / "registry.json"
ENV_VERSION = "LOANLENS_MODEL_VERSION"
SCHEMA_VERSION = 1


class RegistryError(RuntimeError):
    """A registry problem. ``str(error)`` is a plain-English message."""


class ArtifactIntegrityError(RegistryError):
    """The artifact file does not match the SHA-256 recorded in the registry."""


class ModelEntry(BaseModel):
    """One registered model version."""

    model_config = ConfigDict(extra="ignore")

    version: str = Field(pattern=SEMVER)
    created_at: str
    training_data_hash: str
    n_train: int = Field(ge=0)
    features: list[str]
    kind: str = ""
    calibration: str = ""
    cv_metrics: dict[str, float] = Field(default_factory=dict)
    artifact: str = Field(pattern=r"^[A-Za-z0-9_.\-]+\.joblib$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(ge=0)
    status: Literal["active", "archived"]
    notes: str = ""


class Registry(BaseModel):
    """The whole registry file."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = SCHEMA_VERSION
    active: str | None = None
    models: list[ModelEntry] = Field(default_factory=list)

    def get(self, version: str) -> ModelEntry:
        """The entry for ``version``.

        Raises:
            RegistryError: the version is not registered.
        """
        for entry in self.models:
            if entry.version == version:
                return entry
        known = ", ".join(e.version for e in self.models) or "none"
        raise RegistryError(f"Model version {version} is not registered (registered: {known}).")


def _path(registry_path: Path | None) -> Path:
    """The registry file (looked up at call time, so tests can redirect it)."""
    return Path(registry_path) if registry_path is not None else REGISTRY_PATH


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_filename(version: str) -> str:
    """File name of a versioned artifact, e.g. ``loanlens_model_1.0.0.joblib``."""
    if not re.fullmatch(SEMVER, version):
        raise RegistryError(f"'{version}' is not a semantic version such as 1.2.0.")
    return f"loanlens_model_{version}.joblib"


def load_registry(path: Path | None = None) -> Registry:
    """Read the registry (an empty registry if the file does not exist)."""
    path = _path(path)
    if not Path(path).exists():
        return Registry()
    try:
        return Registry.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RegistryError(f"The model registry {Path(path).name} is not valid.") from exc


def save_registry(registry: Registry, path: Path | None = None) -> Path:
    """Write the registry atomically (temporary file, then replace)."""
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry.model_dump(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def next_version(registry: Registry) -> str:
    """The next minor version after the highest registered one (1.0.0 if none)."""
    if not registry.models:
        return "1.0.0"
    major, minor, _ = _version_key(max((e.version for e in registry.models), key=_version_key))
    return f"{major}.{minor + 1}.0"


def register(
    artifact_path: Path,
    meta: dict[str, Any],
    training_data_hash: str,
    activate: bool = True,
    notes: str = "",
    registry_path: Path | None = None,
) -> ModelEntry:
    """Add a saved artifact to the registry (and make it active unless told otherwise).

    Args:
        artifact_path: the saved ``.joblib`` file (must sit next to the registry).
        meta: the artifact's metadata (``version``, ``features``, ``cv_metrics``, ...).
        training_data_hash: SHA-256 of the training data file.
        activate: make this version the active one (others become archived).
        notes: optional free text recorded with the entry.

    Raises:
        RegistryError: the version is already registered.
    """
    registry = load_registry(registry_path)
    version = str(meta["version"])
    if any(e.version == version for e in registry.models):
        raise RegistryError(f"Model version {version} is already registered.")
    artifact_path = Path(artifact_path)
    entry = ModelEntry(
        version=version,
        created_at=str(meta.get("trained_at") or datetime.now(UTC).isoformat(timespec="seconds")),
        training_data_hash=training_data_hash,
        n_train=int(meta.get("n_train", 0)),
        features=list(meta.get("features", [])),
        kind=str(meta.get("kind", "")),
        calibration=str(meta.get("calibration", "")),
        cv_metrics={k: float(v) for k, v in (meta.get("cv_metrics") or {}).items()},
        artifact=artifact_path.name,
        artifact_sha256=file_sha256(artifact_path),
        artifact_bytes=artifact_path.stat().st_size,
        status="archived",
        notes=notes,
    )
    registry.models.append(entry)
    registry.models.sort(key=lambda e: _version_key(e.version))
    if activate or registry.active is None:
        _set_active(registry, version)
    save_registry(registry, registry_path)
    return registry.get(version)


def _set_active(registry: Registry, version: str) -> None:
    registry.get(version)  # raises if unknown
    registry.active = version
    for entry in registry.models:
        entry.status = "active" if entry.version == version else "archived"


def activate(version: str, registry_path: Path | None = None) -> ModelEntry:
    """Make ``version`` the active model; every other version becomes archived.

    The artifact is checked first, so a missing or altered file is never activated.
    """
    registry = load_registry(registry_path)
    entry = registry.get(version)
    verify(entry, _path(registry_path).parent)
    _set_active(registry, version)
    save_registry(registry, registry_path)
    return registry.get(version)


def selected_version(registry: Registry) -> str:
    """``LOANLENS_MODEL_VERSION`` if set, else the active version.

    Raises:
        FileNotFoundError: nothing is registered (with instructions).
        RegistryError: the requested version is not registered.
    """
    wanted = os.environ.get(ENV_VERSION, "").strip()
    if wanted:
        registry.get(wanted)
        return wanted
    if registry.active is None:
        raise FileNotFoundError(
            "No trained model is registered. Run `python -m loanlens.model` to train one."
        )
    return registry.active


def verify(entry: ModelEntry, model_dir: Path | None = None) -> Path:
    """Check that the entry's artifact exists and matches its recorded SHA-256.

    Returns:
        The artifact path.

    Raises:
        FileNotFoundError: the artifact file is missing.
        ArtifactIntegrityError: the file's hash differs from the registry.
    """
    path = (Path(model_dir) if model_dir is not None else _path(None).parent) / entry.artifact
    if not path.exists():
        raise FileNotFoundError(
            f"The model file {entry.artifact} is missing. Run `python -m loanlens.model` to "
            "train a model, or restore the file."
        )
    if file_sha256(path) != entry.artifact_sha256:
        raise ArtifactIntegrityError(
            f"The model file {entry.artifact} does not match the fingerprint recorded in the "
            "model registry, so it was not loaded. Restore the original file or retrain."
        )
    return path


def resolve_artifact(registry_path: Path | None = None) -> tuple[ModelEntry, Path]:
    """The selected version's entry and its verified artifact path."""
    registry = load_registry(registry_path)
    entry = registry.get(selected_version(registry))
    return entry, verify(entry, _path(registry_path).parent)


def format_table(registry: Registry) -> str:
    """Plain-text listing for ``python -m loanlens.model --list``."""
    if not registry.models:
        return "No models are registered yet. Run `python -m loanlens.model` to train one."
    lines = [f"{'version':<10} {'status':<9} {'created_at':<26} {'ROC-AUC':>8} {'F1':>7}  artifact"]
    for e in registry.models:
        auc, f1 = e.cv_metrics.get("roc_auc"), e.cv_metrics.get("f1")
        lines.append(
            f"{e.version:<10} {e.status:<9} {e.created_at:<26} "
            f"{'n/a' if auc is None else f'{auc:.4f}':>8} {'n/a' if f1 is None else f'{f1:.4f}':>7}"
            f"  {e.artifact} (sha256 {e.artifact_sha256[:12]})"
        )
    return "\n".join(lines)
