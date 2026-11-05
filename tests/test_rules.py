"""Tests for loanlens.rules."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from loanlens import features, rules
from loanlens.config import RuleConfig, load_policy

POLICY = load_policy()
R = POLICY.rules
RATE = POLICY.emi.assumed_annual_interest_rate


def applicant(**overrides: float) -> dict[str, float]:
    """A comfortably passing applicant; override fields to test one rule at a time."""
    base = {
        "cibil_score": 750,
        "income_annum": 6_000_000,
        "loan_amount": 6_000_000,
        "loan_term": 20,
        "residential_assets_value": 5_000_000,
        "commercial_assets_value": 2_000_000,
        "luxury_assets_value": 3_000_000,
        "bank_asset_value": 1_000_000,
    }
    base.update(overrides)
    return base


def by_rule(results: list[rules.RuleResult]) -> dict[str, rules.RuleResult]:
    return {r.rule: r for r in results}


# Thresholds come from config
def test_thresholds_come_from_config() -> None:
    results = by_rule(rules.evaluate_rules(applicant()))
    for name, res in results.items():
        assert res.threshold == getattr(R, name).value
        assert res.enforce == getattr(R, name).enforce


def test_custom_threshold_is_respected() -> None:
    assert rules.check_min_cibil(700, RuleConfig(value=720)).passed is False
    assert rules.check_min_cibil(700, RuleConfig(value=650)).passed is True


def test_good_applicant_passes_everything() -> None:
    assert all(r.passed for r in rules.evaluate_rules(applicant()))


# min_cibil
def test_min_cibil_exactly_at_threshold_passes() -> None:
    assert rules.check_min_cibil(R.min_cibil.value, R.min_cibil).passed


def test_min_cibil_below_fails_with_exact_message() -> None:
    res = rules.check_min_cibil(R.min_cibil.value - 1, R.min_cibil)
    assert not res.passed
    assert res.message == (
        f"CIBIL score {R.min_cibil.value - 1:.0f} is below the minimum {R.min_cibil.value:.0f}."
    )
    assert res.actual == R.min_cibil.value - 1


# max_emi_to_income
def test_emi_to_income_exactly_at_threshold_passes() -> None:
    assert rules.check_max_emi_to_income(
        R.max_emi_to_income.value, R.max_emi_to_income, RATE
    ).passed


def test_emi_to_income_above_fails() -> None:
    res = rules.check_max_emi_to_income(R.max_emi_to_income.value + 0.01, R.max_emi_to_income, RATE)
    assert not res.passed and "above" in res.message


def test_emi_to_income_nan_fails() -> None:
    res = rules.check_max_emi_to_income(float("nan"), R.max_emi_to_income, RATE)
    assert not res.passed and "could not be worked out" in res.message


def test_emi_rule_via_applicant() -> None:
    # 2-year loan of 4x income: EMI far above half of monthly income.
    res = by_rule(rules.evaluate_rules(applicant(loan_amount=24_000_000, loan_term=2)))
    assert not res["max_emi_to_income"].passed
    expected = features.emi_to_income(24_000_000, 2, 6_000_000, RATE)
    assert res["max_emi_to_income"].actual == pytest.approx(expected)


# max_loan_to_income
def test_loan_to_income_exactly_at_threshold_passes() -> None:
    income = 1_000_000
    loan = income * R.max_loan_to_income.value
    res = by_rule(rules.evaluate_rules(applicant(income_annum=income, loan_amount=loan)))
    assert res["max_loan_to_income"].passed


def test_loan_to_income_just_above_fails() -> None:
    income = 1_000_000
    loan = income * R.max_loan_to_income.value + 1
    res = by_rule(rules.evaluate_rules(applicant(income_annum=income, loan_amount=loan)))
    assert not res["max_loan_to_income"].passed


def test_zero_income_fails_income_rules_safely() -> None:
    res = by_rule(rules.evaluate_rules(applicant(income_annum=0)))
    assert not res["max_loan_to_income"].passed
    assert not res["max_emi_to_income"].passed
    assert "No annual income" in res["max_loan_to_income"].message


# max_loan_to_assets
def test_loan_to_assets_exactly_at_threshold_passes() -> None:
    a = applicant()
    total = sum(a[c] for c in features.ASSET_COLUMNS)
    res = by_rule(rules.evaluate_rules(applicant(loan_amount=total * R.max_loan_to_assets.value)))
    assert res["max_loan_to_assets"].passed


def test_zero_assets_fails_safely() -> None:
    zero = {c: 0 for c in features.ASSET_COLUMNS}
    res = by_rule(rules.evaluate_rules(applicant(**zero)))
    assert not res["max_loan_to_assets"].passed
    assert math.isinf(res["max_loan_to_assets"].actual)
    assert "No assets" in res["max_loan_to_assets"].message


def test_missing_asset_fields_count_as_zero() -> None:
    a = applicant()
    del a["luxury_assets_value"]
    assert len(rules.evaluate_rules(a)) == 6


# loan term
@pytest.mark.parametrize(
    ("term", "min_ok", "max_ok"),
    [
        (R.min_loan_term_years.value, True, True),
        (R.min_loan_term_years.value - 1, False, True),
        (R.max_loan_term_years.value, True, True),
        (R.max_loan_term_years.value + 1, True, False),
    ],
)
def test_loan_term_limits(term: float, min_ok: bool, max_ok: bool) -> None:
    assert rules.check_min_loan_term(term, R.min_loan_term_years).passed is min_ok
    assert rules.check_max_loan_term(term, R.max_loan_term_years).passed is max_ok


def test_zero_term_fails_min_term_and_emi() -> None:
    res = by_rule(rules.evaluate_rules(applicant(loan_term=0)))
    assert not res["min_loan_term_years"].passed
    assert not res["max_emi_to_income"].passed


# extreme amounts
def test_extreme_loan_amount_fails_ratio_rules() -> None:
    res = by_rule(rules.evaluate_rules(applicant(loan_amount=1e13)))
    assert not res["max_loan_to_income"].passed
    assert not res["max_loan_to_assets"].passed
    assert not res["max_emi_to_income"].passed


def test_tiny_loan_passes_ratio_rules() -> None:
    res = by_rule(rules.evaluate_rules(applicant(loan_amount=1)))
    assert res["max_loan_to_income"].passed and res["max_loan_to_assets"].passed


# enforced vs advisory
def test_enforced_and_advisory_split() -> None:
    results = [
        rules.RuleResult(rule="a", passed=False, actual=1, threshold=0, enforce=True, message="m"),
        rules.RuleResult(rule="b", passed=False, actual=1, threshold=0, enforce=False, message="m"),
        rules.RuleResult(rule="c", passed=True, actual=1, threshold=0, enforce=True, message="m"),
    ]
    assert [r.rule for r in rules.enforced_failures(results)] == ["a"]
    assert [r.rule for r in rules.advisory_failures(results)] == ["b"]


def test_messages_are_non_empty() -> None:
    for res in rules.evaluate_rules(applicant(cibil_score=400, income_annum=0, loan_term=30)):
        assert res.message.strip()


# vectorised version agrees with the scalar functions
def test_rule_pass_frame_matches_scalar() -> None:
    rows = [
        applicant(),
        applicant(cibil_score=549),
        applicant(cibil_score=550),
        applicant(income_annum=0),
        applicant(loan_term=1),
        applicant(loan_term=21),
        applicant(loan_amount=24_000_000, loan_term=2),
        applicant(**{c: 0 for c in features.ASSET_COLUMNS}),
    ]
    frame = rules.rule_pass_frame(pd.DataFrame(rows))
    for i, row in enumerate(rows):
        scalar = {r.rule: r.passed for r in rules.evaluate_rules(row)}
        assert frame.iloc[i].to_dict() == scalar, i


def test_summarise_against_labels() -> None:
    df = pd.DataFrame([applicant(), applicant(cibil_score=400), applicant(cibil_score=400)])
    df["loan_status"] = [1, 1, 0]
    table = rules.summarise_against_labels(df).set_index("rule")
    assert table.loc["min_cibil", "fail_n"] == 2
    assert table.loc["min_cibil", "fail_n_approved"] == 1
    assert table.loc["min_cibil", "fail_share_approved"] == pytest.approx(0.5)
    assert table.loc["min_cibil", "approval_rate_when_failing"] == pytest.approx(0.5)


def test_config_enforce_matches_five_percent_criterion() -> None:
    from loanlens import cleaning

    if not cleaning.PROCESSED_PATH.exists():
        pytest.skip("processed data not available")
    table = rules.summarise_against_labels(pd.read_csv(cleaning.PROCESSED_PATH))
    assert (table["implied_enforce"] == table["configured_enforce"]).all()
