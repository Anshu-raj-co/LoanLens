"""Decision orchestration: the single source of truth for an application's outcome.

Order (CLAUDE.md section 5):
1. validate input (invalid -> :class:`ValidationFailure`, no decision);
2. policy rules (any *enforced* failure -> Rejected; advisory failures -> warnings);
3. calibrated model probability ``p`` (Approved if ``p >= approval_threshold``);
4. borderline flag (probability band, or CIBIL near the enforced minimum);
5. reasons, positive factors and "what would change".

An enforced rule failure always wins: the model can never approve such an applicant.

:func:`decide_many` is the vectorised core used by both customer mode and Bulk Check.
:func:`decide` validates one application and runs the same core on a single row, so an
applicant gets exactly the same result in both modes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from loanlens import explain, rules
from loanlens import model as model_mod
from loanlens.config import Policy, resolve_policy
from loanlens.formatting import inr, score_percent, times
from loanlens.schema import (
    ApplicantInput,
    DecisionResult,
    ValidationFailure,
    validate_applicant,
)

INPUT_COLUMNS: tuple[str, ...] = tuple(ApplicantInput.model_fields)

# Inputs checked against the training range, with display formatting.
RANGE_CHECKS: dict[str, tuple[str, Any]] = {
    "income_annum": ("annual income", inr),
    "loan_amount": ("loan amount", inr),
    "loan_term": ("loan term", lambda v: f"{v:g} years"),
    "loan_to_income": ("loan-to-income ratio", times),
}


def _range_warning(label: str, fmt, value: float, lo: float, hi: float) -> str:
    return (
        f"Your {label} of {fmt(value)} is outside the range seen in the training data "
        f"({fmt(lo)} to {fmt(hi)}), so this result is less reliable."
    )


def _borderline_flags(
    values: pd.DataFrame, passes: pd.DataFrame, proba: np.ndarray, policy: Policy
) -> tuple[np.ndarray, np.ndarray]:
    """Return (probability-band borderline, CIBIL-margin borderline) masks.

    * Probability band: no enforced rule failed and ``p`` is inside the configured band.
    * CIBIL margin (milestone 2 review, decision 3): CIBIL is within
      ``borderline_cibil_margin`` points of an enforced ``min_cibil`` threshold, on either
      side, and no *other* enforced rule failed (manual review cannot override, say, a
      term limit).
    """
    r = policy.rules
    enforced_cols = [c for c in passes.columns if getattr(r, c).enforce]
    other_cols = [c for c in enforced_cols if c != "min_cibil"]
    any_enforced_fail = ~passes[enforced_cols].all(axis=1).to_numpy()
    other_fail = (
        ~passes[other_cols].all(axis=1).to_numpy() if other_cols else np.zeros(len(values), bool)
    )
    band = policy.model.borderline_band
    in_band = ~any_enforced_fail & (proba >= band.lower) & (proba <= band.upper)
    if r.min_cibil.enforce:
        gap = np.abs(values["cibil_score"].to_numpy(dtype="float64") - r.min_cibil.value)
        near = (gap <= policy.model.borderline_cibil_margin) & ~other_fail
    else:
        near = np.zeros(len(values), bool)
    return in_band, near


def decide_many(
    values: pd.DataFrame,
    policy: Policy | None = None,
    artifact: dict[str, Any] | None = None,
    include_positive: bool = True,
    include_rule_results: bool = True,
    profile: str | None = None,
) -> list[DecisionResult]:
    """Decide many *already validated* applications at once.

    Features, rules, model probabilities and SHAP values are computed in vectorised
    passes. Reasons and "what would change" are built only for rejected rows.

    Args:
        values: one row per applicant with the :class:`ApplicantInput` columns.
        policy: policy to apply; when given it wins over ``profile``.
        artifact: trained model artifact; defaults to the active registered model.
        include_positive: build positive factors for approved rows.
        include_rule_results: attach all six rule results to every row (customer mode).
            When False, ``rule_results`` holds only the failed rules.
        profile: loan type whose policy profile to apply (default ``personal``). A profile
            changes the rules and assumptions only; the model is the same for every profile.

    Raises:
        UnknownProfileError: ``profile`` names no profile (clear, user-facing message).
    """
    policy = resolve_policy(profile, policy)
    artifact = artifact or model_mod.load_artifact()
    values = values[list(INPUT_COLUMNS)].reset_index(drop=True)
    n = len(values)
    if n == 0:
        return []
    threshold = policy.model.approval_threshold

    # 2. Rules (vectorised status; scalar results only where messages are needed)
    passes = rules.rule_pass_frame(values, policy)
    enforced_cols = [c for c in passes.columns if getattr(policy.rules, c).enforce]
    enforced_fail = ~passes[enforced_cols].all(axis=1).to_numpy()
    any_fail = ~passes.all(axis=1).to_numpy()

    # 3. Model
    frame = model_mod.build_frame(values)
    proba = model_mod.predict_proba(artifact, frame)
    approved = ~enforced_fail & (proba >= threshold)

    # 4. Borderline
    in_band, near_cibil = _borderline_flags(values, passes, proba, policy)
    borderline = in_band | near_cibil

    # 5. Explanations (batched)
    records = values.to_dict("records")
    rejected_idx = np.flatnonzero(~approved)
    explain_idx = np.flatnonzero(~approved | (approved & include_positive))
    contributions = (
        explain.shap_contributions(artifact, frame.iloc[explain_idx])
        if len(explain_idx)
        else pd.DataFrame()
    )
    contrib_pos = {int(i): k for k, i in enumerate(explain_idx)}
    changes_list = (
        explain.what_would_change_many(values.iloc[rejected_idx], artifact, policy)
        if len(rejected_idx)
        else []
    )
    changes_by_row = {int(i): changes_list[k] for k, i in enumerate(rejected_idx)}
    benchmarks = artifact.get("benchmarks", {})
    ranges = artifact.get("training_ranges", {})
    range_masks = {
        col: (frame[col].to_numpy(dtype="float64"), *ranges[col])
        for col in RANGE_CHECKS
        if col in ranges and col in frame.columns
    }
    margin = policy.model.borderline_cibil_margin
    model_version = str(artifact.get("version", "unknown"))
    min_cibil = policy.rules.min_cibil.value

    results: list[DecisionResult] = []
    for i in range(n):
        p = float(proba[i])
        rule_results = (
            rules.evaluate_rules(records[i], policy)
            if (include_rule_results or any_fail[i])
            else []
        )
        failed = rules.enforced_failures(rule_results)
        advisory = rules.advisory_failures(rule_results)
        if not include_rule_results:
            rule_results = [r for r in rule_results if not r.passed]

        warnings = [f"Advisory check: {r.message}" for r in advisory]
        for col, (vals, lo, hi) in range_masks.items():
            v = vals[i]
            if math.isfinite(v) and (v < lo or v > hi):
                label, fmt = RANGE_CHECKS[col]
                warnings.append(_range_warning(label, fmt, v, lo, hi))
        if in_band[i]:
            warnings.append(
                f"The approval likelihood ({score_percent(p)}) is close to the threshold, so "
                "manual review is recommended."
            )
        if near_cibil[i]:
            warnings.append(
                f"The CIBIL score ({records[i]['cibil_score']}) is within {margin:g} points "
                f"of the minimum of {min_cibil:g}, so manual review is recommended."
            )

        row = frame.iloc[i]
        if not approved[i]:
            contrib = contributions.iloc[contrib_pos[i]]
            model_based = explain.model_reasons(contrib, row, benchmarks, positive=False)
            reasons = explain.merge_reasons(explain.rule_reasons(failed), model_based)
            if not reasons:
                reasons = [explain.overall_reason(p, threshold)]
            positive: list = []
            changes = changes_by_row[i]
        else:
            reasons = []
            positive = (
                explain.positive_factors(contributions.iloc[contrib_pos[i]], row, benchmarks)
                if include_positive
                else []
            )
            changes = []

        results.append(
            DecisionResult(
                status="Approved" if approved[i] else "Rejected",
                probability=p,
                borderline=bool(borderline[i]),
                reasons=reasons,
                positive_factors=positive,
                what_would_change=changes,
                rule_results=rule_results,
                warnings=warnings,
                model_version=model_version,
                profile=policy.profile,
                policy_version=policy.version,
                policy_hash=policy.content_hash,
            )
        )
    return results


def decide(
    data: Mapping[str, Any] | ApplicantInput,
    policy: Policy | None = None,
    artifact: dict[str, Any] | None = None,
    profile: str | None = None,
) -> DecisionResult | ValidationFailure:
    """Score one application and explain the outcome (customer mode).

    Args:
        data: raw applicant fields (dict) or an already validated :class:`ApplicantInput`.
        policy: policy to apply; when given it wins over ``profile``.
        artifact: trained model artifact; defaults to the active registered model.
        profile: loan type (``personal`` by default, or ``home`` / ``vehicle``).

    Returns:
        A :class:`DecisionResult`, or a :class:`ValidationFailure` (and no decision) when
        the input is invalid.

    Raises:
        UnknownProfileError: ``profile`` names no profile.
    """
    policy = resolve_policy(profile, policy)
    applicant = validate_applicant(data)
    if isinstance(applicant, ValidationFailure):
        return applicant
    values = pd.DataFrame([applicant.model_dump()])
    return decide_many(values, policy, artifact)[0]
