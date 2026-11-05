"""Decision orchestration: the single source of truth for an application's outcome.

Order (CLAUDE.md section 5):
1. validate input (invalid -> :class:`ValidationFailure`, no decision);
2. policy rules (any *enforced* failure -> Rejected; advisory failures -> warnings);
3. calibrated model probability ``p`` (Approved if ``p >= approval_threshold``);
4. borderline flag when ``p`` is inside the configured band;
5. reasons, positive factors and "what would change".

An enforced rule failure always wins: the model can never approve such an applicant.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from loanlens import explain, rules
from loanlens import model as model_mod
from loanlens.config import Policy, load_policy
from loanlens.formatting import inr, times
from loanlens.schema import (
    ApplicantInput,
    DecisionResult,
    ValidationFailure,
    validate_applicant,
)

# Inputs checked against the training range, with display formatting.
RANGE_CHECKS: dict[str, tuple[str, Any]] = {
    "income_annum": ("annual income", inr),
    "loan_amount": ("loan amount", inr),
    "loan_term": ("loan term", lambda v: f"{v:g} years"),
    "loan_to_income": ("loan-to-income ratio", times),
}


def _range_warnings(row: pd.Series, ranges: dict[str, tuple[float, float]]) -> list[str]:
    out = []
    for col, (label, fmt) in RANGE_CHECKS.items():
        if col not in ranges or col not in row:
            continue
        lo, hi = ranges[col]
        value = float(row[col])
        if math.isfinite(value) and (value < lo or value > hi):
            out.append(
                f"Your {label} of {fmt(value)} is outside the range seen in the training data "
                f"({fmt(lo)} to {fmt(hi)}), so this result is less reliable."
            )
    return out


def decide(
    data: Mapping[str, Any] | ApplicantInput,
    policy: Policy | None = None,
    artifact: dict[str, Any] | None = None,
) -> DecisionResult | ValidationFailure:
    """Score one application and explain the outcome.

    Args:
        data: raw applicant fields (dict) or an already validated :class:`ApplicantInput`.
        policy: policy to apply; defaults to ``config/policy.yaml``.
        artifact: trained model artifact; defaults to the saved model in ``models/``.

    Returns:
        A :class:`DecisionResult`, or a :class:`ValidationFailure` (and no decision) when
        the input is invalid.
    """
    applicant = validate_applicant(data)
    if isinstance(applicant, ValidationFailure):
        return applicant
    policy = policy or load_policy()
    artifact = artifact or model_mod.load_artifact()
    threshold = policy.model.approval_threshold
    band = policy.model.borderline_band

    # 2. Policy rules
    values = applicant.model_dump()
    rule_results = rules.evaluate_rules(values, policy)
    enforced = rules.enforced_failures(rule_results)
    advisory = rules.advisory_failures(rule_results)

    # 3. Model
    frame = model_mod.build_frame(pd.DataFrame([values]))
    probability = float(model_mod.predict_proba(artifact, frame)[0])
    if enforced:
        status = "Rejected"
    else:
        status = "Approved" if probability >= threshold else "Rejected"

    # 4. Borderline (only meaningful when no hard rule has already decided)
    borderline = not enforced and band.lower <= probability <= band.upper

    # Warnings
    warnings = [f"Advisory check: {r.message}" for r in advisory]
    warnings += _range_warnings(frame.iloc[0], artifact.get("training_ranges", {}))
    if borderline:
        warnings.append(
            f"The approval likelihood ({probability:.0%}) is close to the threshold, so "
            "manual review is recommended."
        )

    # 5. Reasons
    contributions = explain.shap_contributions(artifact, frame).iloc[0]
    benchmarks = artifact.get("benchmarks", {})
    row = frame.iloc[0]
    if status == "Rejected":
        model_based = explain.model_reasons(contributions, row, benchmarks, positive=False)
        reasons = explain.merge_reasons(explain.rule_reasons(enforced), model_based)
        if not reasons:
            reasons = [explain.overall_reason(probability, threshold)]
        positive: list = []
        changes = explain.what_would_change(applicant, artifact, policy)
    else:
        reasons = []
        positive = explain.positive_factors(contributions, row, benchmarks)
        changes = []

    return DecisionResult(
        status=status,
        probability=probability,
        borderline=borderline,
        reasons=reasons,
        positive_factors=positive,
        what_would_change=changes,
        rule_results=rule_results,
        warnings=warnings,
        model_version=str(artifact.get("version", "unknown")),
    )
