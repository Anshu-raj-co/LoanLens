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
