"""Tests for loanlens.decision and loanlens.explain (decision engine end to end)."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from loanlens import explain
from loanlens.config import RuleConfig, load_policy
from loanlens.decision import decide
from loanlens.schema import DecisionResult, Reason, ValidationFailure

STRONG = {
    "cibil_score": 780,
    "income_annum": 6_000_000,
    "loan_amount": 15_000_000,
    "loan_term": 10,
    "residential_assets_value": 12_000_000,
    "commercial_assets_value": 4_000_000,
    "luxury_assets_value": 10_000_000,
    "bank_asset_value": 5_000_000,
}
BORDERLINE = {
    "cibil_score": 693,
    "income_annum": 2_700_000,
    "loan_amount": 10_100_000,
    "loan_term": 20,
    "residential_assets_value": 2_500_000,
    "commercial_assets_value": 1_200_000,
    "luxury_assets_value": 4_000_000,
    "bank_asset_value": 1_500_000,
}
NEGATIVE_CODES = {"LOW_CIBIL", "HIGH_LOAN_TO_INCOME", "LOWER_INCOME", "LOW_ASSETS"}


def run(data: dict, **kw) -> DecisionResult:
    res = decide(data, **kw)
    assert isinstance(res, DecisionResult), res
    return res


@pytest.fixture(scope="module")
def many_applicants(clean_df: pd.DataFrame) -> list[dict]:
    """Real rows (stratified sample) plus hand-made edge cases."""
    sample = pd.concat(
        [
            clean_df[clean_df["loan_status"] == 0].sample(120, random_state=3),
            clean_df[clean_df["loan_status"] == 1].sample(80, random_state=3),
        ]
    )
    rows = sample.drop(columns=["loan_status"]).to_dict("records")
    rows += [
        {**STRONG, "cibil_score": 549},
        {**STRONG, "cibil_score": 550},
        {**STRONG, "loan_amount": 30_000_000},  # 5x income
        {**STRONG, "loan_term": 25},
        {**STRONG, "loan_term": 1},
        {**STRONG, "loan_amount": 1e10},
        {**STRONG, **{k: 0 for k in STRONG if k.endswith("_value")}},
        BORDERLINE,
    ]
    return rows


@pytest.fixture(scope="module")
def many_results(many_applicants, artifact) -> list[DecisionResult]:
    return [run(a) for a in many_applicants]


# Required properties ---------------------------------------------------------------------


def test_every_rejection_has_a_non_empty_reason(many_results) -> None:
    rejected = [r for r in many_results if r.status == "Rejected"]
    assert rejected, "sample should contain rejections"
    for r in rejected:
        assert r.reasons, r
        for reason in r.reasons:
            assert reason.message.strip() and reason.code.strip()
            assert reason.your_value.strip() and reason.benchmark.strip()
            assert reason.suggestion.strip()


def test_approved_results_have_no_rejection_reasons(many_results) -> None:
    approved = [r for r in many_results if r.status == "Approved"]
    assert approved
    for r in approved:
        assert r.reasons == []
        assert r.what_would_change == []
        assert r.positive_factors, "approved results get at least one positive factor"
        assert not any(
            f.code in NEGATIVE_CODES or f.code.startswith("RULE_") for f in r.positive_factors
        )
        assert not any(not rr.passed and rr.enforce for rr in r.rule_results)


def test_invalid_input_returns_error_and_no_decision() -> None:
    res = decide({"cibil_score": 1000, "income_annum": "abc"})
    assert isinstance(res, ValidationFailure)
    assert not hasattr(res, "status") and not hasattr(res, "probability")
    fields = {e.field for e in res.errors}
    assert {"cibil_score", "income_annum", "loan_amount", "loan_term"} <= fields
    assert all(e.message.strip() for e in res.errors)


def test_results_are_deterministic(artifact) -> None:
    for applicant in (STRONG, BORDERLINE, {**STRONG, "cibil_score": 480}):
        first = run(applicant).model_dump()
        for _ in range(3):
            assert run(applicant).model_dump() == first


# Decision logic --------------------------------------------------------------------------


def test_enforced_rule_always_overrides_model(many_results) -> None:
    for r in many_results:
        if any(rr.enforce and not rr.passed for rr in r.rule_results):
            assert r.status == "Rejected"
            assert r.reasons[0].source == "rule"
            assert r.borderline is False


def test_min_cibil_overrides_otherwise_perfect_profile(artifact) -> None:
    res = run({**STRONG, "cibil_score": 549})
    assert res.status == "Rejected"
    assert res.reasons[0].code == "RULE_MIN_CIBIL"
    assert res.reasons[0].message == "CIBIL score 549 is below the minimum 550."
    assert run({**STRONG, "cibil_score": 550}).status == "Approved"


def test_model_threshold_decides_when_rules_pass(many_results) -> None:
    thr = load_policy().model.approval_threshold
    for r in many_results:
        if not any(rr.enforce and not rr.passed for rr in r.rule_results):
            assert r.status == ("Approved" if r.probability >= thr else "Rejected")


def test_advisory_rule_warns_but_does_not_reject(artifact) -> None:
    # 2-year term: EMI far above 50% of income (advisory), everything else strong.
    res = run({**STRONG, "loan_term": 2})
    emi = next(rr for rr in res.rule_results if rr.rule == "max_emi_to_income")
    assert not emi.passed and not emi.enforce
    assert any(w.startswith("Advisory check:") for w in res.warnings)
    assert not any(r.code == "RULE_MAX_EMI_TO_INCOME" for r in res.reasons)


def test_disabling_enforcement_changes_outcome(artifact) -> None:
    policy = load_policy()
    relaxed = policy.model_copy(
        update={
            "rules": policy.rules.model_copy(
                update={"min_cibil": RuleConfig(value=550, enforce=False)}
            )
        }
    )
    res = run({**STRONG, "cibil_score": 540}, policy=relaxed)
    assert not any(r.code == "RULE_MIN_CIBIL" for r in res.reasons)
    assert any("CIBIL score 540 is below" in w for w in res.warnings)


def test_borderline_flag(artifact) -> None:
    band = load_policy().model.borderline_band
    res = run(BORDERLINE)
    assert band.lower <= res.probability <= band.upper
    assert res.borderline is True
    assert any("manual review" in w for w in res.warnings)
    assert run(STRONG).borderline is False


def test_out_of_range_warning(artifact) -> None:
    res = run({**STRONG, "income_annum": 20_000_000, "loan_amount": 40_000_000})
    assert any("annual income" in w and "outside the range" in w for w in res.warnings)
    assert not any("outside the range" in w for w in run(STRONG).warnings)


def test_reasons_capped_and_ranked(many_results) -> None:
    for r in many_results:
        assert len(r.reasons) <= explain.MAX_REASONS
        sources = [x.source for x in r.reasons]
        assert sources == sorted(sources, key=lambda s: s != "rule")  # rules first


def test_approved_gets_positive_factors(artifact) -> None:
    res = run(STRONG)
    assert res.status == "Approved"
    assert 1 <= len(res.positive_factors) <= explain.MAX_POSITIVE
    assert res.positive_factors[0].code == "STRONG_CIBIL"


def test_loan_term_never_used_as_model_reason(many_results) -> None:
    for r in many_results:
        for reason in [*r.reasons, *r.positive_factors]:
            if reason.source == "model":
                assert "repayment period" not in reason.message
                assert "term" not in reason.code.lower()


def test_output_contains_all_fields(artifact) -> None:
    dumped = run(STRONG).model_dump()
    for key in (
        "status",
        "probability",
        "borderline",
        "reasons",
        "what_would_change",
        "rule_results",
        "warnings",
    ):
        assert key in dumped
    assert len(dumped["rule_results"]) == 6


def test_decision_is_fast(artifact) -> None:
    run(BORDERLINE)  # warm-up
    start = time.perf_counter()
    run({**STRONG, "cibil_score": 480})  # rejection: includes the what-would-change search
    assert time.perf_counter() - start < 2.0


# What would change (review decision 5) -----------------------------------------------------


def test_what_would_change_only_raises_cibil_or_lowers_loan(many_applicants, many_results):
    seen = 0
    for applicant, r in zip(many_applicants, many_results, strict=True):
        for c in r.what_would_change:
            seen += 1
            assert c.feature in {"cibil_score", "loan_amount"}
            if c.feature == "cibil_score":
                assert c.suggested_value > applicant["cibil_score"]
                assert c.suggested_value <= 900
            else:
                assert 0 < c.suggested_value < applicant["loan_amount"]
            assert "would likely" in c.message
            text = c.message.lower()
            assert "guarantee" not in text and "term" not in text
            assert "increas" not in text or "loan" not in text
    assert seen > 0


def test_suggested_changes_actually_flip_the_decision(many_applicants, many_results) -> None:
    checked = 0
    for applicant, r in zip(many_applicants, many_results, strict=True):
        for c in r.what_would_change:
            changed = run({**applicant, c.feature: c.suggested_value})
            assert changed.status == "Approved", (applicant, c)
            checked += 1
            if checked >= 40:
                return


def test_no_change_suggested_for_term_rule(artifact) -> None:
    res = run({**STRONG, "loan_term": 25})
    assert res.status == "Rejected"
    assert res.what_would_change == []  # only a term change would help, which is never offered
    assert "No single change" in explain.change_summary(res.what_would_change)


def test_change_summary_wording() -> None:
    from loanlens.schema import Change

    text = explain.change_summary(
        [
            Change(feature="cibil_score", current_value=600, suggested_value=700, message="m"),
            Change(feature="loan_amount", current_value=5e6, suggested_value=4e6, message="m"),
        ]
    )
    assert text == (
        "Raising your CIBIL score to about 700, or reducing the loan to about "
        "Rs 40,00,000 would likely change the result."
    )


# Reason merging --------------------------------------------------------------------------


def _reason(code: str, source: str, weight: float) -> Reason:
    return Reason(
        code=code,
        message="m",
        your_value="v",
        benchmark="b",
        suggestion="s",
        source=source,
        weight=weight,
    )


def test_merge_reasons_dedupes_and_caps() -> None:
    rule = [_reason("RULE_MIN_CIBIL", "rule", 1000)]
    model = [_reason("LOW_CIBIL", "model", 3.0)] + [
        _reason(f"X{i}", "model", float(i)) for i in range(10)
    ]
    merged = explain.merge_reasons(rule, model)
    assert merged[0].code == "RULE_MIN_CIBIL"
    assert "LOW_CIBIL" not in [m.code for m in merged]  # already covered by the rule
    assert len(merged) == explain.MAX_REASONS
    assert [m.weight for m in merged[1:]] == sorted([m.weight for m in merged[1:]], reverse=True)


def test_model_reasons_respect_direction() -> None:
    contributions = pd.Series({"income_annum": -1.0, "cibil_score": -1.0})
    row = pd.Series({"income_annum": 9_000_000.0, "cibil_score": 600.0})
    bench = {"income_annum": 5_000_000.0, "cibil_score": 711.0}
    reasons = explain.model_reasons(contributions, row, bench, positive=False)
    # High income is never called a weakness, even if its SHAP value is negative.
    assert [r.code for r in reasons] == ["LOW_CIBIL"]
    assert np.isclose(reasons[0].weight, 1.0)
