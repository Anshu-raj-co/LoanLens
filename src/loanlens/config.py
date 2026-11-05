"""Typed loader for ``config/policy.yaml`` (the single source of all thresholds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "config" / "policy.yaml"


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
    """The whole policy file."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    rules: RulesConfig
    emi: EmiConfig
    model: ModelConfig
    display: DisplayConfig = DisplayConfig()
    batch: BatchConfig = BatchConfig()
    storage: StorageConfig = StorageConfig()


def load_policy_file(path: Path = POLICY_PATH) -> Policy:
    """Read and validate a policy YAML file."""
    with open(path, encoding="utf-8") as fh:
        return Policy.model_validate(yaml.safe_load(fh) or {})


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    """Return the project policy (cached; the file is read once per process)."""
    return load_policy_file(POLICY_PATH)
