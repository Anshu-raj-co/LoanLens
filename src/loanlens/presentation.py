"""Display-ready views of decisions (no Streamlit here, so it can be unit tested).

The Streamlit pages only lay out what these functions return.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from loanlens import explain
from loanlens.config import Policy
from loanlens.formatting import SCORE_LABEL, inr, likelihood_band, likelihood_text, pct, times
from loanlens.registry import Registry
from loanlens.rules import RuleResult
from loanlens.schema import ApplicantInput, Change, DecisionResult, Reason

PROTOTYPE_NOTICE = "Prototype - not a lending decision"
DISCLAIMER = (
    "LoanLens is a pre-screening and decision-support prototype. It estimates the loan "
    "**approval decision** learned from public, synthetic data. It does **not** predict "
    "default (whether a loan would be repaid), it is not a lending decision, and no "
    "real-world accuracy is claimed."
)
PRIVACY_NOTE = (
    "Nothing you enter on this page is stored or logged. The result is calculated in memory "
    "and discarded when you leave the page."
)

BENCHMARK_SUMMARY = (
    "LoanLens was also tested on a second, larger public synthetic dataset "
    "(`bank_loan_data.csv`, 45,000 applicants, amounts that look like US dollars, FICO-style "
    "credit scores up to 850). It was used only for comparison: it was not merged with the "
    "training data and did not change the model.\n\n"
    "- **Different dominant feature:** here CIBIL decides most outcomes; there, a *previous "
    "loan default* does (every applicant with one was rejected), and credit score had no "
    "effect at all.\n"
    "- **Performance:** about 0.98 ROC-AUC there (with class weights, because only 22% were "
    "approved) against about 0.99 here. Both are high only because each synthetic dataset "
    "follows one rule-like field.\n"
    "- **Lesson:** a real system should also collect previous defaults, employment "
    "experience, home ownership, loan purpose, the offered interest rate and existing EMIs.\n\n"
    "Full comparison: `reports/benchmark.md`."
)


@dataclass(frozen=True)
class FormField:
    """One customer-form input."""

    name: str
    label: str
    min_value: int
    max_value: int
    step: int
    default: int
    help: str
    is_amount: bool


FORM_FIELDS: tuple[FormField, ...] = (
    FormField(
        "cibil_score", "CIBIL score", 300, 900, 1, 700,
        "Your credit score from CIBIL, between 300 and 900.", False,
    ),
    FormField(
        "income_annum", "Annual income (Rs)", 0, 500_000_000, 50_000, 5_000_000,
        "Total yearly income before tax, in rupees.", True,
    ),
    FormField(
        "loan_amount", "Loan amount requested (Rs)", 0, 1_000_000_000, 100_000, 15_000_000,
        "The amount you want to borrow, in rupees.", True,
    ),
    FormField(
        "loan_term", "Loan term (years)", 1, 30, 1, 10,
        "Repayment period in whole years.", False,
    ),
    FormField(
        "residential_assets_value", "Residential property (Rs)", 0, 2_000_000_000, 100_000,
        5_000_000, "Value of homes or residential land you own. Enter 0 if none.", True,
    ),
    FormField(
        "commercial_assets_value", "Commercial property (Rs)", 0, 2_000_000_000, 100_000,
        3_000_000, "Value of shops, offices or commercial land you own. Enter 0 if none.", True,
    ),
    FormField(
        "luxury_assets_value", "Luxury assets (Rs)", 0, 2_000_000_000, 100_000, 10_000_000,
        "Value of vehicles, jewellery and similar assets. Enter 0 if none.", True,
    ),
    FormField(
        "bank_asset_value", "Bank balances and deposits (Rs)", 0, 2_000_000_000, 100_000,
        4_000_000, "Savings, fixed deposits and investments. Enter 0 if none.", True,
    ),
)  # fmt: skip

RULE_LABELS: dict[str, str] = {
    "min_cibil": "Minimum CIBIL score",
    "max_emi_to_income": "Maximum EMI as a share of monthly income",
    "max_loan_to_income": "Maximum loan as a multiple of annual income",
    "max_loan_to_assets": "Maximum loan as a multiple of total assets",
    "min_loan_term_years": "Minimum loan term",
    "max_loan_term_years": "Maximum loan term",
}


def thresholds_note(policy: Policy) -> str:
    """The "illustrative placeholders" notice (milestone 2 review, decision 5)."""
    r = policy.rules
    return (
        "All policy thresholds used here are **illustrative placeholders** until replaced by a "
        "lender's real credit policy: minimum CIBIL "
        f"{r.min_cibil.value:.0f}, maximum loan {times(r.max_loan_to_income.value)} annual "
        f"income, maximum loan {times(r.max_loan_to_assets.value)} total assets, maximum EMI "
        f"{pct(r.max_emi_to_income.value)} of monthly income, loan term "
        f"{r.min_loan_term_years.value:g} to {r.max_loan_term_years.value:g} years, and an "
        f"assumed interest rate of {policy.emi.assumed_annual_interest_rate:.0%} a year."
    )


def _rule_value(rule: str, value: float) -> str:
    if rule == "min_cibil":
        return f"{value:.0f}"
    if rule == "max_emi_to_income":
        return pct(value)
    if rule in {"max_loan_to_income", "max_loan_to_assets"}:
        return times(value)
    return f"{value:g} year" if value == 1 else f"{value:g} years"


def policy_table(policy: Policy) -> pd.DataFrame:
    """Current policy settings for display (About page)."""
    rows = []
    for name, label in RULE_LABELS.items():
        cfg = getattr(policy.rules, name)
        rows.append(
            {
                "Rule": label,
                "Config key": name,
                "Value": _rule_value(name, cfg.value),
                "Enforced": "Yes (fails reject)" if cfg.enforce else "No (advisory warning)",
                "Status": "Placeholder",
            }
        )
    band = policy.model.borderline_band
    bands = policy.display.probability_bands
    rows += [
        {
            "Rule": "Assumed annual interest rate (for EMI)",
            "Config key": "emi.assumed_annual_interest_rate",
            "Value": f"{policy.emi.assumed_annual_interest_rate:.1%}",
            "Enforced": "-",
            "Status": "Placeholder",
        },
        {
            "Rule": "Model approval threshold",
            "Config key": "model.approval_threshold",
            "Value": f"{policy.model.approval_threshold:.0%}",
            "Enforced": "-",
            "Status": "Placeholder",
        },
        {
            "Rule": "Borderline probability band",
            "Config key": "model.borderline_band",
            "Value": f"{band.lower:.0%} to {band.upper:.0%}",
            "Enforced": "-",
            "Status": "Placeholder",
        },
        {
            "Rule": "Borderline CIBIL margin",
            "Config key": "model.borderline_cibil_margin",
            "Value": f"+/- {policy.model.borderline_cibil_margin:g} points",
            "Enforced": "-",
            "Status": "Placeholder",
        },
        {
            "Rule": "Likelihood bands (lower bounds)",
            "Config key": "display.probability_bands",
            "Value": (
                f"Very likely {bands.very_likely:.0%}, Likely {bands.likely:.0%}, "
                f"Borderline {bands.borderline:.0%}, Unlikely {bands.unlikely:.0%}"
            ),
            "Enforced": "-",
            "Status": "Placeholder",
        },
    ]
    return pd.DataFrame(rows)


PROFILE_NOTE = (
    "Loan types change the policy rules and assumptions (term limits, income and asset "
    "multiples, and the assumed interest rate), not the trained model. Every loan type is "
    "scored by the same model, which learned from one synthetic dataset with no loan-type "
    "information."
)


def profile_label(name: str) -> str:
    """Display name of a loan type, e.g. 'Home loan'."""
    return f"{name.replace('_', ' ').capitalize()} loan"


def profile_caption(policy: Policy) -> str:
    """One line naming the profile, its version and short hash (shown with a result)."""
    return (
        f"Loan type: {profile_label(policy.profile)} (policy profile v{policy.version}, "
        f"settings hash {policy.content_hash[:12]})."
    )


def profiles_table(policies: Mapping[str, Policy]) -> pd.DataFrame:
    """Every profile's settings side by side (About page): one column per loan type."""
    table: pd.DataFrame | None = None
    for name, policy in policies.items():
        part = policy_table(policy)[["Rule", "Config key", "Value"]].rename(
            columns={"Value": f"{profile_label(name)} (v{policy.version})"}
        )
        if table is None:
            enforced = policy_table(policy)["Enforced"]
            table = part.assign(Enforced=enforced.to_numpy())
        else:
            table = table.merge(part, on=["Rule", "Config key"], how="left")
    if table is None:
        return pd.DataFrame(columns=["Rule", "Config key", "Enforced"])
    cols = ["Rule", "Config key"] + [c for c in table.columns if c.endswith(")")] + ["Enforced"]
    return table[cols]


def registry_table(registry: Registry) -> pd.DataFrame:
    """Registered model versions for display (About page), newest first."""
    rows = [
        {
            "Version": e.version,
            "Status": e.status.capitalize(),
            "Created (UTC)": e.created_at,
            "Training rows": e.n_train,
            "CV ROC-AUC": e.cv_metrics.get("roc_auc"),
            "CV F1": e.cv_metrics.get("f1"),
            "Artifact SHA-256 (start)": e.artifact_sha256[:12],
            "Training data SHA-256 (start)": e.training_data_hash[:12],
        }
        for e in reversed(registry.models)
    ]
    columns = [
        "Version", "Status", "Created (UTC)", "Training rows", "CV ROC-AUC", "CV F1",
        "Artifact SHA-256 (start)", "Training data SHA-256 (start)",
    ]  # fmt: skip
    return pd.DataFrame(rows, columns=columns)


@dataclass
class DecisionView:
    """Everything the customer page shows for one result."""

    status: str
    approved: bool
    headline: str
    likelihood: str
    band: str
    score_label: str
    borderline: bool
    borderline_note: str
    reasons: list[Reason] = field(default_factory=list)
    positives: list[Reason] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    change_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    rule_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    notice: str = PROTOTYPE_NOTICE


def _rule_rows(results: list[RuleResult]) -> pd.DataFrame:
    rows = [
        {
            "Check": RULE_LABELS.get(r.rule, r.rule),
            "Result": "Pass" if r.passed else ("Fail" if r.enforce else "Advisory"),
            "Details": r.message,
        }
        for r in results
    ]
    return pd.DataFrame(rows, columns=["Check", "Result", "Details"])


def present(result: DecisionResult, policy: Policy) -> DecisionView:
    """Turn a :class:`DecisionResult` into display-ready text (never shows 0% or 100%)."""
    bands = policy.display.probability_bands
    approved = result.status == "Approved"
    rule_rejected = any(r.enforce and not r.passed for r in result.rule_results)
    if approved:
        headline = "Likely to be approved"
    elif rule_rejected:
        headline = "Likely to be rejected (a policy rule was not met)"
    else:
        headline = "Likely to be rejected"
    warnings = [w for w in result.warnings if "manual review is recommended" not in w]
    review = [w for w in result.warnings if "manual review is recommended" in w]
    return DecisionView(
        status=result.status,
        approved=approved,
        headline=headline,
        likelihood=likelihood_text(result.probability, bands),
        band=likelihood_band(result.probability, bands),
        score_label=SCORE_LABEL,
        borderline=result.borderline,
        borderline_note=" ".join(review) if result.borderline else "",
        reasons=list(result.reasons),
        positives=list(result.positive_factors),
        changes=list(result.what_would_change),
        change_summary=explain.change_summary(result.what_would_change) if not approved else "",
        warnings=warnings,
        rule_rows=_rule_rows(result.rule_results),
    )


def amount_hint(value: float) -> str:
    """Indian-grouped echo of an amount typed into a number box, e.g. 'Rs 12,50,000'."""
    return inr(value)


def form_defaults() -> dict[str, int]:
    """Default value of every form field."""
    return {f.name: f.default for f in FORM_FIELDS}


def form_matches_schema() -> bool:
    """True if the form collects exactly the fields the decision engine needs."""
    return [f.name for f in FORM_FIELDS] == list(ApplicantInput.model_fields)


def borderline_explainer(policy: Policy) -> str:
    """Plain-language explanation of the borderline flag (About page; mirrored in USER_GUIDE)."""
    band = policy.model.borderline_band
    margin = policy.model.borderline_cibil_margin
    min_cibil = policy.rules.min_cibil.value
    bands = policy.display.probability_bands
    return (
        "A result is marked **borderline - manual review recommended** when it is too close "
        "to call. The result itself is still *Approved* or *Rejected*; the flag only suggests "
        "that a person should take a second look. It is raised in two situations:\n\n"
        f"1. **The model score is close to the cut-off:** between {band.lower:.0%} and "
        f"{band.upper:.0%}, and no enforced policy rule was failed.\n"
        f"2. **The CIBIL score is close to the minimum:** within {margin:g} points of "
        f"{min_cibil:.0f} on either side (so {min_cibil - margin:.0f} to "
        f"{min_cibil + margin:.0f}). A score of {min_cibil - 10:.0f} is rejected by the "
        "CIBIL rule but flagged, because a small difference in the score could change the "
        "outcome.\n\n"
        "**Why a CIBIL score near the minimum is not flagged when another rule also failed:** "
        "if the application also breaks a different enforced rule (for example a loan term "
        "longer than the maximum, or a loan far above the income limit), it would be rejected "
        "even with a better CIBIL score. A manual review of the CIBIL score could not change "
        "that result, so flagging it as borderline would be misleading.\n\n"
        "The verbal likelihood band shown next to the score (for example *Borderline* for "
        f"{bands.borderline:.0%}-{bands.likely:.0%}) is a separate, wider display label; only "
        "the flag above means *manual review recommended*. All of these values are "
        "placeholders in the policy profiles in `config/policies/`."
    )
