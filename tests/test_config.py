"""Tests for loanlens.config and loanlens.formatting."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from loanlens.config import POLICY_PATH, load_policy, load_policy_file
from loanlens.formatting import group_indian, inr, pct, times


def test_project_policy_loads() -> None:
    policy = load_policy()
    assert policy.rules.min_cibil.value == 550
    assert policy.rules.min_cibil.enforce is True
    assert policy.model.borderline_band.lower <= policy.model.borderline_band.upper


def test_every_value_marked_placeholder() -> None:
    text = POLICY_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#")[0].strip()
        if stripped.startswith(
            ("value:", "enforce:", "assumed_annual", "approval_threshold", "lower:", "upper:")
        ):
            assert "PLACEHOLDER" in line, line


def test_invalid_band_rejected(tmp_path: Path) -> None:
    text = POLICY_PATH.read_text(encoding="utf-8").replace("lower: 0.4", "lower: 0.9")
    bad = tmp_path / "policy.yaml"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_policy_file(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (999, "999"),
        (1000, "1,000"),
        (125000, "1,25,000"),
        (1250000, "12,50,000"),
        (123456789, "12,34,56,789"),
        (-150000, "-1,50,000"),
    ],
)
def test_group_indian(value: float, expected: str) -> None:
    assert group_indian(value) == expected


def test_other_formatters() -> None:
    assert inr(1250000) == "Rs 12,50,000"
    assert times(3.25) == "3.2x" or times(3.25) == "3.3x"
    assert pct(0.475) in {"47%", "48%"}
    assert times(float("inf")) == "n/a" and pct(float("nan")) == "n/a"


def test_score_percent_never_shows_extremes() -> None:
    from loanlens.formatting import score_percent

    assert score_percent(1.0) == ">99%" and score_percent(0.995) == ">99%"
    assert score_percent(0.0) == "<1%" and score_percent(0.004) == "<1%"
    assert score_percent(0.5) == "50%" and score_percent(0.99) == "99%"
    for p in [i / 1000 for i in range(1001)]:
        assert score_percent(p) not in {"0%", "100%"}


@pytest.mark.parametrize(
    ("p", "band"),
    [
        (0.0, "Very unlikely"),
        (0.149, "Very unlikely"),
        (0.15, "Unlikely"),
        (0.35, "Borderline"),
        (0.649, "Borderline"),
        (0.65, "Likely"),
        (0.85, "Very likely"),
        (1.0, "Very likely"),
    ],
)
def test_likelihood_band(p: float, band: str) -> None:
    from loanlens.formatting import likelihood_band, likelihood_text

    bands = load_policy().display.probability_bands
    assert likelihood_band(p, bands) == band
    assert likelihood_text(p, bands).endswith(band)


def test_bands_must_descend() -> None:
    from loanlens.config import ProbabilityBands

    with pytest.raises(ValidationError):
        ProbabilityBands(very_likely=0.5, likely=0.6, borderline=0.3, unlikely=0.1)
