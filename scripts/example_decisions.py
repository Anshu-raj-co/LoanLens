"""Print five example decisions and save them to ``reports/example_decisions.md``.

The applicants are hypothetical (not real people). Run with:
    python scripts/example_decisions.py
"""

from __future__ import annotations

from pathlib import Path

from loanlens import explain
from loanlens.decision import decide
from loanlens.formatting import inr
from loanlens.schema import DecisionResult

OUT = Path(__file__).resolve().parents[1] / "reports" / "example_decisions.md"

EXAMPLES: list[tuple[str, dict[str, float]]] = [
    (
        "Approved: strong profile",
        {
            "cibil_score": 780,
            "income_annum": 6_000_000,
            "loan_amount": 15_000_000,
            "loan_term": 10,
            "residential_assets_value": 12_000_000,
            "commercial_assets_value": 4_000_000,
            "luxury_assets_value": 10_000_000,
            "bank_asset_value": 5_000_000,
        },
    ),
    (
        "Approved: moderate CIBIL, ratio within range",
        {
            "cibil_score": 640,
            "income_annum": 2_500_000,
            "loan_amount": 7_500_000,
            "loan_term": 15,
            "residential_assets_value": 3_000_000,
            "commercial_assets_value": 1_000_000,
            "luxury_assets_value": 3_000_000,
            "bank_asset_value": 1_000_000,
        },
    ),
    (
        "Rejected: CIBIL below the policy minimum",
        {
            "cibil_score": 480,
            "income_annum": 5_000_000,
            "loan_amount": 15_000_000,
            "loan_term": 10,
            "residential_assets_value": 8_000_000,
            "commercial_assets_value": 3_000_000,
            "luxury_assets_value": 9_000_000,
            "bank_asset_value": 4_000_000,
        },
    ),
    (
        "Rejected: loan too large for income and assets",
        {
            "cibil_score": 720,
            "income_annum": 1_200_000,
            "loan_amount": 6_000_000,
            "loan_term": 15,
            "residential_assets_value": 2_000_000,
            "commercial_assets_value": 0,
            "luxury_assets_value": 1_000_000,
            "bank_asset_value": 500_000,
        },
    ),
    (
        "Borderline: close to the approval threshold",
        {
            "cibil_score": 693,
            "income_annum": 2_700_000,
            "loan_amount": 10_100_000,
            "loan_term": 20,
            "residential_assets_value": 2_500_000,
            "commercial_assets_value": 1_200_000,
            "luxury_assets_value": 4_000_000,
            "bank_asset_value": 1_500_000,
        },
    ),
]

LABELS = {
    "cibil_score": ("CIBIL score", lambda v: f"{v:.0f}"),
    "income_annum": ("Annual income", inr),
    "loan_amount": ("Loan amount", inr),
    "loan_term": ("Loan term", lambda v: f"{v:g} years"),
    "residential_assets_value": ("Residential assets", inr),
    "commercial_assets_value": ("Commercial assets", inr),
    "luxury_assets_value": ("Luxury assets", inr),
    "bank_asset_value": ("Bank assets", inr),
}


def likelihood(p: float) -> str:
    """Display a probability without implying certainty (isotonic output can be 0 or 1)."""
    if p > 0.99:
        return ">99%"
    if p < 0.01:
        return "<1%"
    return f"{p:.0%}"


def render(title: str, applicant: dict[str, float], result: DecisionResult) -> str:
    """Format one decision as Markdown text."""
    flag = " (borderline: manual review recommended)" if result.borderline else ""
    lines = [f"## {title}", "", "**Applicant (hypothetical)**", ""]
    lines += [f"- {LABELS[k][0]}: {LABELS[k][1](v)}" for k, v in applicant.items()]
    lines += [
        "",
        f"**Result: {result.status.upper()}**{flag}",
        f"Approval likelihood: {likelihood(result.probability)} "
        f"(model v{result.model_version})",
        "",
    ]
    if result.reasons:
        lines.append("**Reasons**")
        lines.append("")
        for i, r in enumerate(result.reasons, 1):
            lines.append(f"{i}. {r.message}")
            lines.append(f"   - Your value: {r.your_value}. Benchmark: {r.benchmark}.")
            if r.suggestion:
                lines.append(f"   - Suggestion: {r.suggestion}")
        lines.append("")
    if result.positive_factors:
        lines.append("**What is working in your favour**")
        lines.append("")
        lines += [f"- {r.message}" for r in result.positive_factors]
        lines.append("")
    if result.status == "Rejected":
        lines.append("**What would likely change this**")
        lines.append("")
        lines.append(explain.change_summary(result.what_would_change))
        lines.append("")
    lines.append("**Policy checks**")
    lines.append("")
    for r in result.rule_results:
        mark = "pass" if r.passed else ("FAIL" if r.enforce else "advisory")
        lines.append(f"- [{mark}] {r.message}")
    if result.warnings:
        lines += ["", "**Warnings**", ""]
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines) + "\n"


def main() -> None:
    """Score every example, print the text and write the Markdown report."""
    parts = [
        "# Example decisions",
        "",
        "Generated by `python scripts/example_decisions.py`. The applicants are "
        "hypothetical. LoanLens is a pre-screening prototype that estimates the "
        "**approval decision** in synthetic data. It is not a lending decision and does "
        "not predict default. All policy thresholds are placeholders.",
        "",
    ]
    for title, applicant in EXAMPLES:
        result = decide(applicant)
        if not isinstance(result, DecisionResult):  # pragma: no cover
            raise RuntimeError(f"Example '{title}' failed validation: {result}")
        text = render(title, applicant, result)
        print(text)
        parts.append(text)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
