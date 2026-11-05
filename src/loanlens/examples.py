"""Hypothetical example applicants (not real people).

The first five are the Phase 5 examples; the sixth shows the CIBIL-margin borderline
rule. Used by ``scripts/example_decisions.py`` (``reports/example_decisions.md``) and by the
customer-mode tests. Each entry is ``(title, applicant fields, expected outcome)``.
"""

from __future__ import annotations

from typing import TypedDict


class Expected(TypedDict):
    """Expected outcome of an example."""

    status: str
    borderline: bool


EXAMPLES: list[tuple[str, dict[str, float], Expected]] = [
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
        {"status": "Approved", "borderline": False},
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
        {"status": "Approved", "borderline": False},
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
        {"status": "Rejected", "borderline": False},
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
        {"status": "Rejected", "borderline": False},
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
        {"status": "Rejected", "borderline": True},
    ),
    (
        "Borderline: CIBIL just below the minimum (added for review decision 3)",
        {
            "cibil_score": 540,
            "income_annum": 6_000_000,
            "loan_amount": 15_000_000,
            "loan_term": 10,
            "residential_assets_value": 12_000_000,
            "commercial_assets_value": 4_000_000,
            "luxury_assets_value": 10_000_000,
            "bank_asset_value": 5_000_000,
        },
        {"status": "Rejected", "borderline": True},
    ),
]
