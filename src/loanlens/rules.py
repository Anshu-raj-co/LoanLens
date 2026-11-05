"""Policy rules (CLAUDE.md section 5). Every threshold comes from ``config/policy.yaml``.

Each ``check_*`` function evaluates one rule for one applicant and returns a
:class:`RuleResult`. A value exactly at the threshold passes. A value that cannot
be computed (``nan``) fails, so missing information never slips through.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict

from loanlens import features
from loanlens.config import Policy, RuleConfig, load_policy
from loanlens.formatting import pct, times

_PRECISION = 9  # round ratios before comparing, so 4.0000000001 does not fail a 4.0 cap


class RuleResult(BaseModel):
    """Outcome of one policy rule for one applicant."""

    model_config = ConfigDict(frozen=True)

    rule: str
    passed: bool
    actual: float
    threshold: float
    enforce: bool
    message: str


def _at_least(actual: float, threshold: float) -> bool:
    return not math.isnan(actual) and round(actual, _PRECISION) >= threshold


def _at_most(actual: float, threshold: float) -> bool:
    return not math.isnan(actual) and round(actual, _PRECISION) <= threshold


def check_min_cibil(cibil_score: float, rule: RuleConfig) -> RuleResult:
    """CIBIL score must be at least the minimum."""
    passed = _at_least(cibil_score, rule.value)
    msg = (
        f"CIBIL score {cibil_score:.0f} meets the minimum of {rule.value:.0f}."
        if passed
        else f"CIBIL score {cibil_score:.0f} is below the minimum {rule.value:.0f}."
    )
    return RuleResult(
        rule="min_cibil",
        passed=passed,
        actual=float(cibil_score),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def check_max_emi_to_income(ratio: float, rule: RuleConfig, annual_rate: float) -> RuleResult:
    """Monthly EMI must not exceed the allowed share of monthly income."""
    passed = _at_most(ratio, rule.value)
    if math.isnan(ratio):
        msg = "The monthly EMI could not be worked out because the loan term is not valid."
    elif passed:
        msg = (
            f"The estimated EMI is {pct(ratio)} of monthly income, within the "
            f"{pct(rule.value)} limit."
        )
    else:
        msg = (
            f"The estimated EMI would take {pct(ratio)} of monthly income, above the "
            f"{pct(rule.value)} limit (assuming {annual_rate:.1%} annual interest)."
        )
    return RuleResult(
        rule="max_emi_to_income",
        passed=passed,
        actual=float(ratio),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def check_max_loan_to_income(ratio: float, rule: RuleConfig) -> RuleResult:
    """Loan amount must not exceed a multiple of annual income."""
    passed = _at_most(ratio, rule.value)
    if math.isinf(ratio):
        msg = "No annual income was given, so the loan cannot be compared with income."
    elif passed:
        msg = f"The loan is {times(ratio)} annual income, within the {times(rule.value)} limit."
    else:
        msg = (
            f"The loan is {times(ratio)} annual income, above the maximum of "
            f"{times(rule.value)}."
        )
    return RuleResult(
        rule="max_loan_to_income",
        passed=passed,
        actual=float(ratio),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def check_max_loan_to_assets(ratio: float, rule: RuleConfig) -> RuleResult:
    """Loan amount must not exceed a multiple of total declared assets."""
    passed = _at_most(ratio, rule.value)
    if math.isinf(ratio):
        msg = "No assets were declared, so the loan is not covered by any assets."
    elif passed:
        msg = f"The loan is {times(ratio)} total assets, within the {times(rule.value)} limit."
    else:
        msg = (
            f"The loan is {times(ratio)} total declared assets, above the maximum of "
            f"{times(rule.value)}."
        )
    return RuleResult(
        rule="max_loan_to_assets",
        passed=passed,
        actual=float(ratio),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def check_min_loan_term(term_years: float, rule: RuleConfig) -> RuleResult:
    """Loan term must be at least the minimum number of years."""
    passed = _at_least(term_years, rule.value)
    msg = (
        f"Loan term of {term_years:g} years meets the minimum of {rule.value:g} years."
        if passed
        else f"Loan term of {term_years:g} years is shorter than the minimum {rule.value:g} years."
    )
    return RuleResult(
        rule="min_loan_term_years",
        passed=passed,
        actual=float(term_years),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def check_max_loan_term(term_years: float, rule: RuleConfig) -> RuleResult:
    """Loan term must not exceed the maximum number of years."""
    passed = _at_most(term_years, rule.value)
    msg = (
        f"Loan term of {term_years:g} years is within the maximum of {rule.value:g} years."
        if passed
        else f"Loan term of {term_years:g} years is longer than the maximum {rule.value:g} years."
    )
    return RuleResult(
        rule="max_loan_term_years",
        passed=passed,
        actual=float(term_years),
        threshold=rule.value,
        enforce=rule.enforce,
        message=msg,
    )


def evaluate_rules(
    applicant: Mapping[str, float], policy: Policy | None = None
) -> list[RuleResult]:
    """Run every policy rule for one applicant.

    Args:
        applicant: raw inputs (``cibil_score``, ``income_annum``, ``loan_amount``,
            ``loan_term`` and the four asset columns).
        policy: policy to apply; defaults to ``config/policy.yaml``.
    """
    policy = policy or load_policy()
    r = policy.rules
    rate = policy.emi.assumed_annual_interest_rate
    loan, income, term = applicant["loan_amount"], applicant["income_annum"], applicant["loan_term"]
    assets = sum(float(applicant.get(c, 0) or 0) for c in features.ASSET_COLUMNS)
    return [
        check_min_cibil(float(applicant["cibil_score"]), r.min_cibil),
        check_max_emi_to_income(
            features.emi_to_income(loan, term, income, rate), r.max_emi_to_income, rate
        ),
        check_max_loan_to_income(features.loan_to_income(loan, income), r.max_loan_to_income),
        check_max_loan_to_assets(features.loan_to_assets(loan, assets), r.max_loan_to_assets),
        check_min_loan_term(float(term), r.min_loan_term_years),
        check_max_loan_term(float(term), r.max_loan_term_years),
    ]


def enforced_failures(results: list[RuleResult]) -> list[RuleResult]:
    """Return the failed rules that are enforced (these force a rejection)."""
    return [res for res in results if res.enforce and not res.passed]


def advisory_failures(results: list[RuleResult]) -> list[RuleResult]:
    """Return the failed rules that are advisory only (shown as warnings)."""
    return [res for res in results if not res.enforce and not res.passed]


def rule_pass_frame(df: pd.DataFrame, policy: Policy | None = None) -> pd.DataFrame:
    """Vectorised pass/fail for every rule over many applicants (same semantics as above).

    Returns a boolean frame with one column per rule, aligned with ``df``.
    """
    policy = policy or load_policy()
    r = policy.rules
    feats = features.add_features(df, policy.emi.assumed_annual_interest_rate)

    def at_most(s: pd.Series, thr: float) -> pd.Series:
        return s.round(_PRECISION).le(thr)

    def at_least(s: pd.Series, thr: float) -> pd.Series:
        return s.round(_PRECISION).ge(thr)

    return pd.DataFrame(
        {
            "min_cibil": at_least(feats["cibil_score"].astype(float), r.min_cibil.value),
            "max_emi_to_income": at_most(feats["emi_to_income"], r.max_emi_to_income.value),
            "max_loan_to_income": at_most(feats["loan_to_income"], r.max_loan_to_income.value),
            "max_loan_to_assets": at_most(feats["loan_to_assets"], r.max_loan_to_assets.value),
            "min_loan_term_years": at_least(
                feats["loan_term"].astype(float), r.min_loan_term_years.value
            ),
            "max_loan_term_years": at_most(
                feats["loan_term"].astype(float), r.max_loan_term_years.value
            ),
        },
        index=df.index,
    )


ENFORCE_MAX_APPROVED_SHARE = 0.05  # review decision: enforce a ratio rule only if it fails <5%
RATIO_RULES: tuple[str, ...] = ("max_emi_to_income", "max_loan_to_income", "max_loan_to_assets")


def summarise_against_labels(df: pd.DataFrame, policy: Policy | None = None) -> pd.DataFrame:
    """Compare each rule's failures with historical approval labels.

    Args:
        df: cleaned frame with a 0/1 ``loan_status`` column.
        policy: policy to apply; defaults to ``config/policy.yaml``.

    Returns:
        One row per rule with failure counts overall, among approved and among
        rejected applicants, the approval rate among failures, and the enforce
        setting implied by the <5%-of-approved criterion (ratio rules only).
    """
    policy = policy or load_policy()
    passes = rule_pass_frame(df, policy)
    approved = df["loan_status"] == 1
    rows = []
    for rule in passes.columns:
        fails = ~passes[rule]
        cfg: RuleConfig = getattr(policy.rules, rule)
        share_approved = float(fails[approved].mean())
        rows.append(
            {
                "rule": rule,
                "threshold": cfg.value,
                "fail_n": int(fails.sum()),
                "fail_share_all": float(fails.mean()),
                "fail_n_approved": int(fails[approved].sum()),
                "fail_share_approved": share_approved,
                "fail_n_rejected": int(fails[~approved].sum()),
                "fail_share_rejected": float(fails[~approved].mean()),
                "approval_rate_when_failing": (
                    float(df.loc[fails, "loan_status"].mean()) if fails.any() else float("nan")
                ),
                "implied_enforce": (
                    share_approved < ENFORCE_MAX_APPROVED_SHARE if rule in RATIO_RULES else True
                ),
                "configured_enforce": cfg.enforce,
            }
        )
    return pd.DataFrame(rows)


def _write_report(path: str = "reports/rules_vs_labels.md") -> None:  # pragma: no cover
    """Write the rules-vs-labels markdown report for a lender's credit-policy team to review."""
    from loanlens import cleaning

    policy = load_policy()
    df = pd.read_csv(cleaning.PROCESSED_PATH)
    table = summarise_against_labels(df, policy)
    n_app, n_rej = int(df["loan_status"].sum()), int((df["loan_status"] == 0).sum())

    def share(x: float) -> str:
        return "n/a" if math.isnan(x) else f"{x:.1%}"

    lines = [
        "# Policy rules vs historical approval labels",
        "",
        "Generated by `python -m loanlens.rules` from `data/processed/loan_approval_clean.csv` "
        f"({len(df):,} applicants: {n_app:,} approved, {n_rej:,} rejected).",
        "",
        "All thresholds are **placeholders** from `config/policy.yaml`, illustrative until replaced by "
        "a lender's real credit policy. The labels are *approval decisions* in synthetic data, not "
        "repayment outcomes, so this table shows agreement with past decisions, not risk.",
        "",
        f"EMI assumes {policy.emi.assumed_annual_interest_rate:.1%} annual interest "
        "(placeholder; the dataset has no rate).",
        "",
        "## Share of applicants each rule would reject",
        "",
        "| Rule | Threshold | Fails (all) | Fails among approved | Fails among rejected "
        "| Approval rate when failing | Implied enforce (<5% of approved) | Configured enforce |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in table.itertuples():
        lines.append(
            f"| `{r.rule}` | {r.threshold:g} | {r.fail_n:,} ({share(r.fail_share_all)}) "
            f"| {r.fail_n_approved:,} ({share(r.fail_share_approved)}) "
            f"| {r.fail_n_rejected:,} ({share(r.fail_share_rejected)}) "
            f"| {share(r.approval_rate_when_failing)} | {r.implied_enforce} "
            f"| {r.configured_enforce} |"
        )
    lines += [
        "",
        '"Implied enforce" applies the review rule to the three ratio rules: enforce only if '
        "the rule would reject fewer than 5% of applicants who were actually approved. "
        "`min_cibil` and the loan-term limits are enforced by decision regardless.",
        "",
        "## Enforcement choices",
        "",
    ]
    for r in table.itertuples():
        if r.rule in RATIO_RULES:
            why = (
                f"fails {share(r.fail_share_approved)} of approved applicants "
                f"({'below' if r.implied_enforce else 'at or above'} the 5% limit)"
            )
        else:
            why = "enforced by review decision"
            if r.rule == "min_cibil":
                why += (
                    f"; it would reject {r.fail_n_approved:,} applicants "
                    f"({share(r.fail_share_approved)}) who were approved in the data"
                )
        lines.append(f"- `{r.rule}`: enforce = **{r.configured_enforce}** ({why}).")

    lines += [
        "",
        "## Sensitivity: EMI-to-income cap",
        "",
        "Share of approved applicants whose estimated EMI would exceed each cap, at three "
        "assumed interest rates. Short terms (2 to 4 years) on loans of 1.5 to 4 times annual "
        "income produce EMIs above monthly income, which is why the 50% cap conflicts with "
        "the labels.",
        "",
        "| Cap | 8% rate | 10% rate | 12% rate |",
        "|---|---|---|---|",
    ]
    approved = df["loan_status"] == 1
    for cap in (0.5, 0.75, 1.0, 1.5, 2.0):
        cells = []
        for rate in (0.08, 0.10, 0.12):
            ratio = features.emi_to_income(
                df["loan_amount"], df["loan_term"], df["income_annum"], rate
            )
            cells.append(share(float((ratio[approved] > cap).mean())))
        lines.append(f"| {cap:.0%} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Notes for a lender's credit-policy team to review",
        "",
        "- `max_loan_to_income` (4.0) and `max_loan_to_assets` (1.5) reject nobody in this "
        "data: loan-to-income tops out at exactly 4.0 and loan-to-assets at about 1.33. They "
        "act as guards for inputs outside the training range, not as filters on it.",
        "- The loan-term limits (2 to 20 years) match the data range exactly.",
        "- `max_emi_to_income` is advisory only. A real FOIR-style cap would need the real "
        "interest rate and the applicant's existing EMIs, which the dataset lacks.",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":  # pragma: no cover
    _write_report()
