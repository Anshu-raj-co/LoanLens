"""Typed loader for the policy profiles in ``config/policies/`` (the source of all thresholds).

Each loan type (``personal``, ``home``, ``vehicle``) has one YAML file with ``profile``,
``version`` (semantic version), ``description`` and the rule, EMI, model and display settings.
``personal`` is the default and reproduces the original ``config/policy.yaml`` exactly.
A profile changes the rules and assumptions only, never the trained model.

Every loaded policy carries a content hash (SHA-256 of its validated settings), so a
decision can record exactly which settings produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import cached_property, lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "config" / "policies"
DEFAULT_PROFILE = "personal"
POLICY_PATH = PROFILES_DIR / f"{DEFAULT_PROFILE}.yaml"  # the default profile's file
SEMVER = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class UnknownProfileError(ValueError):
    """Raised for a loan type with no profile file. ``str(error)`` is user-facing."""


class RuleConfig(BaseModel):
    """One policy rule: its threshold and whether a failure is enforced."""

    model_config = ConfigDict(frozen=True)

    value: float
    enforce: bool = True


class RulesConfig(BaseModel):
    """All policy rules."""

    model_config = ConfigDict(frozen=True)

    min_cibil: RuleConfig
    max_emi_to_income: RuleConfig
    max_loan_to_income: RuleConfig
    max_loan_to_assets: RuleConfig
    min_loan_term_years: RuleConfig
    max_loan_term_years: RuleConfig


class BorderlineBand(BaseModel):
    """Probability band in which manual review is recommended."""

    model_config = ConfigDict(frozen=True)

    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> BorderlineBand:
        if self.lower > self.upper:
            raise ValueError("borderline_band.lower must not exceed upper")
        return self


class ModelConfig(BaseModel):
    """Model decision settings."""

    model_config = ConfigDict(frozen=True)

    approval_threshold: float = Field(ge=0, le=1)
    borderline_band: BorderlineBand
    borderline_cibil_margin: float = Field(default=25, ge=0)


class ProbabilityBands(BaseModel):
    """Lower bounds of the verbal likelihood bands (display only)."""

    model_config = ConfigDict(frozen=True)

    very_likely: float = Field(default=0.85, ge=0, le=1)
    likely: float = Field(default=0.65, ge=0, le=1)
    borderline: float = Field(default=0.35, ge=0, le=1)
    unlikely: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def _descending(self) -> ProbabilityBands:
        if not self.very_likely > self.likely > self.borderline > self.unlikely:
            raise ValueError("probability_bands must be strictly decreasing")
        return self


class DisplayConfig(BaseModel):
    """How results are shown."""

    model_config = ConfigDict(frozen=True)

    probability_bands: ProbabilityBands = ProbabilityBands()


class BatchConfig(BaseModel):
    """Bulk Check limits."""

    model_config = ConfigDict(frozen=True)

    max_rows: int = Field(default=50_000, gt=0)
    chunk_size: int = Field(default=2_000, gt=0)


class StorageConfig(BaseModel):
    """SQLite storage of anonymised batch summaries."""

    model_config = ConfigDict(frozen=True)

    db_path: str = "data/loanlens.sqlite"
    store_applicant_ids: bool = False


class EmiConfig(BaseModel):
    """EMI assumptions."""

    model_config = ConfigDict(frozen=True)

    assumed_annual_interest_rate: float = Field(ge=0, lt=1)


class Policy(BaseModel):
    """One policy profile (the whole YAML file)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    profile: str = Field(default=DEFAULT_PROFILE, pattern=_PROFILE_NAME.pattern)
    version: str = Field(default="1.0.0", pattern=SEMVER)
    description: str = ""
    rules: RulesConfig
    emi: EmiConfig
    model: ModelConfig
    display: DisplayConfig = DisplayConfig()
    batch: BatchConfig = BatchConfig()
    storage: StorageConfig = StorageConfig()

    @cached_property
    def content_hash(self) -> str:
        """SHA-256 of the validated settings (canonical JSON). Comments do not affect it."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_policy_file(path: Path = POLICY_PATH) -> Policy:
    """Read and validate a policy YAML file (and compute its content hash)."""
    with open(path, encoding="utf-8") as fh:
        policy = Policy.model_validate(yaml.safe_load(fh) or {})
    _ = policy.content_hash
    return policy


def list_profiles() -> list[str]:
    """Available loan types: the default first, then the others alphabetically."""
    names = sorted(p.stem for p in PROFILES_DIR.glob("*.yaml") if _PROFILE_NAME.fullmatch(p.stem))
    return sorted(names, key=lambda n: (n != DEFAULT_PROFILE, n))


def normalise_profile(name: str | None) -> str:
    """Lower-case, trimmed profile name (``None`` or blank means the default)."""
    text = (name or "").strip().lower()
    return text or DEFAULT_PROFILE


def load_profile(name: str | None = None) -> Policy:
    """Load one policy profile by name (case and spaces ignored; cached per process).

    Raises:
        UnknownProfileError: no such profile (the message lists the valid names).
    """
    key = normalise_profile(name)
    if not _PROFILE_NAME.fullmatch(key) or not (PROFILES_DIR / f"{key}.yaml").is_file():
        raise UnknownProfileError(
            f"Unknown loan type '{name}'. Choose one of: {', '.join(list_profiles())}."
        )
    return _load_profile(key)


@lru_cache(maxsize=16)
def _load_profile(key: str) -> Policy:
    path = PROFILES_DIR / f"{key}.yaml"
    policy = load_policy_file(path)
    if policy.profile != key:
        raise ValueError(f"{path.name} declares profile '{policy.profile}', expected '{key}'")
    return policy


def load_all_profiles() -> dict[str, Policy]:
    """Every profile, keyed by name, default first."""
    return {name: load_profile(name) for name in list_profiles()}


def resolve_policy(profile: str | None = None, policy: Policy | None = None) -> Policy:
    """The policy to apply: an explicit ``policy`` wins, else the named (or default) profile."""
    return policy if policy is not None else load_profile(profile)


def load_policy() -> Policy:
    """Return the default (personal) profile (cached; the file is read once per process)."""
    return load_profile(DEFAULT_PROFILE)
