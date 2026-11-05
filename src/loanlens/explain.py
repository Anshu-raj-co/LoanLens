"""Explanations: SHAP drivers in plain English, rule reasons, and "what would change".

SHAP values are computed on the single uncalibrated XGBoost model inside the calibrated
artifact (calibration is a monotone transform, so the ranking of drivers is unchanged).
Wording is deliberately cautious: results "would likely" change, never "will".
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import shap

from loanlens import model as model_mod
from loanlens import rules
from loanlens.config import Policy
from loanlens.formatting import inr, pct, times
from loanlens.schema import ApplicantInput, Change, Reason

MIN_SHAP = 0.25  # ignore drivers smaller than this (log-odds) as noise
MAX_REASONS = 5
MAX_POSITIVE = 3
CIBIL_STEP = 5
LOAN_STEPS = np.round(np.arange(0.99, 0.095, -0.01), 2)  # 99% down to 10% of the request
LOAN_ROUNDING = 10_000  # suggested loan amounts are rounded down to this

RULE_FEATURE = {
    "min_cibil": "cibil_score",
    "max_loan_to_income": "loan_to_income",
    "max_emi_to_income": "loan_to_income",
    "max_loan_to_assets": "total_assets",
    "min_loan_term_years": "loan_term",
    "max_loan_term_years": "loan_term",
}
RULE_SUGGESTION = {
    "min_cibil": "Paying every EMI and card bill on time and keeping card usage low usually "
    "improves a CIBIL score over a few months.",
    "max_loan_to_income": "A smaller loan amount would bring this within the limit.",
    "max_emi_to_income": "A smaller loan amount would lower the monthly EMI.",
    "max_loan_to_assets": "A smaller loan, or declaring all assets you own, would help.",
    "min_loan_term_years": "Please speak to a loan officer about the repayment period.",
    "max_loan_term_years": "Please speak to a loan officer about the repayment period.",
}


@dataclass(frozen=True)
class _Template:
    """How to describe one model feature."""

    code_neg: str
    code_pos: str
    good_direction: int  # +1 higher is better, -1 lower is better, 0 no clear direction
    fmt: Callable[[float], str]
    negative: str
    positive: str
    suggestion: str


# loan_term is a model feature but is deliberately never turned into a reason or a positive
# factor: its effect comes from the synthetic short-term quirk, and citing it would hint at
# "choose a different term", which LoanLens must never suggest (decisions_log D-026).
TEMPLATES: dict[str, _Template] = {
    "cibil_score": _Template(
        "LOW_CIBIL",
        "STRONG_CIBIL",
        +1,
        lambda v: f"{v:.0f}",
        "Your CIBIL score of {you} is lower than is typical for approved applicants "
        "(around {bench}).",
        "Your CIBIL score of {you} works in favour of this application.",
        RULE_SUGGESTION["min_cibil"],
    ),
    "loan_to_income": _Template(
        "HIGH_LOAN_TO_INCOME",
        "AFFORDABLE_LOAN",
        -1,
        times,
        "The loan you asked for is {you} your annual income; approved applicants typically "
        "borrow around {bench}.",
        "The loan is a manageable {you} your annual income.",
        "A smaller loan amount would lower this ratio.",
    ),
    "income_annum": _Template(
        "LOWER_INCOME",
        "GOOD_INCOME",
        +1,
        inr,
        "Your annual income of {you} is below that of a typical approved applicant "
        "(around {bench}).",
        "Your annual income of {you} supports this application.",
        "Make sure every regular source of income is included in the application.",
    ),
    "total_assets": _Template(
        "LOW_ASSETS",
        "STRONG_ASSETS",
        +1,
        inr,
        "Your declared assets of {you} are lower than those of a typical approved applicant "
        "(around {bench}).",
        "Your declared assets of {you} support this application.",
        "Make sure all assets you own (property, deposits, investments) are declared.",
    ),
}

_EXPLAINERS: dict[int, shap.TreeExplainer] = {}


def _explainer(artifact: dict[str, Any]) -> shap.TreeExplainer:
    key = id(artifact["model"])
    if key not in _EXPLAINERS:
        _EXPLAINERS[key] = shap.TreeExplainer(model_mod.base_pipeline(artifact)[-1])
    return _EXPLAINERS[key]


def shap_contributions(artifact: dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    """SHAP contribution (log-odds) of each model feature, one row per applicant."""
    base = model_mod.base_pipeline(artifact)
    X = base[:-1].transform(frame[artifact["features"]])
    values = _explainer(artifact).shap_values(X)
    return pd.DataFrame(np.asarray(values), columns=X.columns, index=frame.index)


def _worse_than_benchmark(direction: int, value: float, bench: float) -> bool:
    return direction == 0 or (value < bench if direction > 0 else value > bench)


def model_reasons(
    contributions: pd.Series,
    row: pd.Series,
    benchmarks: dict[str, float],
    positive: bool,
    min_shap: float = MIN_SHAP,
) -> list[Reason]:
    """Translate SHAP contributions into reasons (negative) or positive factors.

    A negative driver is used only if it is large enough and the applicant's value is on
    the weaker side of the approved-applicant benchmark, so a reason never says something
    like "your income is too low" for a high income. Positive factors only need a positive
    contribution of at least ``min_shap``; their wording makes no benchmark comparison.
    """
    out: list[Reason] = []
    for feature, value in contributions.items():
        tpl = TEMPLATES.get(str(feature))
        if tpl is None or abs(value) < min_shap or value == 0 or (value > 0) != positive:
            continue
        you, bench = float(row[feature]), float(benchmarks.get(str(feature), math.nan))
        if not positive and not _worse_than_benchmark(tpl.good_direction, you, bench):
            continue
        text = tpl.positive if positive else tpl.negative
        out.append(
            Reason(
                code=tpl.code_pos if positive else tpl.code_neg,
                message=text.format(you=tpl.fmt(you), bench=tpl.fmt(bench)),
                your_value=tpl.fmt(you),
                benchmark=tpl.fmt(bench),
                suggestion="" if positive else tpl.suggestion,
                source="model",
                weight=float(abs(value)),
            )
        )
    return sorted(out, key=lambda r: -r.weight)


def positive_factors(
    contributions: pd.Series, row: pd.Series, benchmarks: dict[str, float]
) -> list[Reason]:
    """Top positive factors for an approval (at least one whenever any driver helped)."""
    factors = model_reasons(contributions, row, benchmarks, positive=True)
    if not factors:
        factors = model_reasons(contributions, row, benchmarks, positive=True, min_shap=0.0)
    return factors[:MAX_POSITIVE]


def _rule_value(res: rules.RuleResult) -> tuple[str, str]:
    if res.rule == "min_cibil":
        return f"{res.actual:.0f}", f"at least {res.threshold:.0f}"
    if res.rule == "max_emi_to_income":
        return pct(res.actual), f"at most {pct(res.threshold)}"
    if res.rule in {"max_loan_to_income", "max_loan_to_assets"}:
        return times(res.actual), f"at most {times(res.threshold)}"
    bound = "at least" if res.rule.startswith("min") else "at most"
    return f"{res.actual:g} years", f"{bound} {res.threshold:g} years"


def rule_reasons(failed: list[rules.RuleResult]) -> list[Reason]:
    """Reasons for failed enforced rules. They outrank every model reason."""
    out = []
    for i, res in enumerate(failed):
        you, bench = _rule_value(res)
        out.append(
            Reason(
                code=f"RULE_{res.rule.upper()}",
                message=res.message,
                your_value=you,
                benchmark=bench,
                suggestion=RULE_SUGGESTION[res.rule],
                source="rule",
                weight=1000.0 - i,
            )
        )
    return out


def merge_reasons(rule_based: list[Reason], model_based: list[Reason]) -> list[Reason]:
    """Rules first, then model drivers not already covered by a rule; at most 5."""
    covered = {
        RULE_FEATURE[r.code.removeprefix("RULE_").lower()] for r in rule_based if r.source == "rule"
    }
    codes_by_feature = {tpl.code_neg: feat for feat, tpl in TEMPLATES.items()}
    extra = [r for r in model_based if codes_by_feature.get(r.code) not in covered]
    merged = sorted(rule_based, key=lambda r: -r.weight) + sorted(extra, key=lambda r: -r.weight)
    return merged[:MAX_REASONS]


def overall_reason(probability: float, threshold: float) -> Reason:
    """Fallback when a rejection has no single dominant driver."""
    return Reason(
        code="OVERALL_PROFILE",
        message=(
            "Taken together, the details in this application are less like past approved "
            "applications than the approval threshold requires."
        ),
        your_value=f"{probability:.0%} approval likelihood",
        benchmark=f"at least {threshold:.0%}",
        suggestion="A higher CIBIL score or a smaller loan amount would likely help.",
        source="model",
        weight=0.0,
    )


# What would change -----------------------------------------------------------------------


def _approved_mask(
    candidates: pd.DataFrame, artifact: dict[str, Any], policy: Policy
) -> np.ndarray:
    """Full decision (enforced rules, then model threshold) for many candidate inputs."""
    passes = rules.rule_pass_frame(candidates, policy)
    enforced = [name for name in passes.columns if getattr(policy.rules, name).enforce]
    rules_ok = passes[enforced].all(axis=1).to_numpy()
    proba = model_mod.predict_proba(artifact, model_mod.build_frame(candidates))
    return rules_ok & (proba >= policy.model.approval_threshold)


def _cibil_candidates(score: float) -> list[int]:
    start = int(math.ceil((score + 1) / CIBIL_STEP) * CIBIL_STEP)
    values = list(range(start, 901, CIBIL_STEP))
    if values and values[-1] != 900:
        values.append(900)
    if not values and score < 900:
        values = [900]
    return values


def _loan_candidates(amount: float) -> list[float]:
    amounts = np.floor(amount * LOAN_STEPS / LOAN_ROUNDING) * LOAN_ROUNDING
    return [float(a) for a in dict.fromkeys(amounts) if 0 < a < amount]


def _first_approved(
    values: pd.DataFrame,
    feature: str,
    candidates: list[list[float]],
    artifact: dict[str, Any],
    policy: Policy,
) -> dict[int, float]:
    """For each row, the first candidate value (in list order) that would be approved."""
    counts = np.array([len(c) for c in candidates])
    if counts.sum() == 0:
        return {}
    owner = np.repeat(np.arange(len(values)), counts)
    flat = np.concatenate([np.asarray(c, dtype="float64") for c in candidates if len(c)])
    expanded = values.iloc[owner].reset_index(drop=True)
    expanded[feature] = flat
    ok = _approved_mask(expanded, artifact, policy)
    hits = pd.DataFrame({"owner": owner[ok], "value": flat[ok]})
    return hits.groupby("owner", sort=False)["value"].first().to_dict()


def what_would_change_many(
    values: pd.DataFrame, artifact: dict[str, Any], policy: Policy
) -> list[list[Change]]:
    """Smallest single change that would likely turn each rejection into an approval.

    Searches one feature at a time and only in directions that make lending sense:
    **raising the CIBIL score** (steps of 5, up to 900) or **reducing the loan amount**
    (99% down to 10% of the request, rounded down to Rs 10,000). It never suggests a bigger
    loan or a different loan term (milestone 1 review, decision 5). Every candidate is
    scored with the full decision (enforced rules, then model) in one vectorised pass.

    Args:
        values: validated applicant inputs, one row per rejected applicant.
    """
    values = values.reset_index(drop=True)
    cibil_hits = _first_approved(
        values,
        "cibil_score",
        [_cibil_candidates(v) for v in values["cibil_score"]],
        artifact,
        policy,
    )
    loan_hits = _first_approved(
        values,
        "loan_amount",
        [_loan_candidates(v) for v in values["loan_amount"]],
        artifact,
        policy,
    )
    out: list[list[Change]] = []
    for i in range(len(values)):
        changes = []
        if i in cibil_hits:
            target = int(cibil_hits[i])
            changes.append(
                Change(
                    feature="cibil_score",
                    current_value=float(values.at[i, "cibil_score"]),
                    suggested_value=target,
                    message=f"Raising your CIBIL score to about {target} would likely "
                    "change the result.",
                )
            )
        if i in loan_hits:
            target = loan_hits[i]
            changes.append(
                Change(
                    feature="loan_amount",
                    current_value=float(values.at[i, "loan_amount"]),
                    suggested_value=target,
                    message=f"Reducing the loan amount to about {inr(target)} would likely "
                    "change the result.",
                )
            )
        out.append(changes)
    return out


def what_would_change(
    applicant: ApplicantInput, artifact: dict[str, Any], policy: Policy
) -> list[Change]:
    """Single-applicant version of :func:`what_would_change_many` (same code path)."""
    return what_would_change_many(pd.DataFrame([applicant.model_dump()]), artifact, policy)[0]


def change_summary(changes: list[Change]) -> str:
    """One sentence combining the suggested changes, e.g. for display."""
    if not changes:
        return (
            "No single change to the CIBIL score or loan amount would likely change this "
            "result on its own."
        )
    parts = []
    for c in changes:
        if c.feature == "cibil_score":
            parts.append(f"raising your CIBIL score to about {c.suggested_value:.0f}")
        else:
            parts.append(f"reducing the loan to about {inr(c.suggested_value)}")
    text = ", or ".join(parts)
    return text[0].upper() + text[1:] + " would likely change the result."
