"""Tests for loanlens.schema (input validation)."""

from __future__ import annotations

import math

import pytest

from loanlens.schema import ApplicantInput, ValidationFailure, validate_applicant

GOOD = {
    "cibil_score": 720,
    "income_annum": 2_400_000,
    "loan_amount": 6_000_000,
    "loan_term": 10,
    "residential_assets_value": 3_000_000,
    "commercial_assets_value": 0,
    "luxury_assets_value": 1_000_000,
    "bank_asset_value": 500_000,
}


def errors_for(data: dict) -> dict[str, str]:
    res = validate_applicant(data)
    assert isinstance(res, ValidationFailure)
    return {e.field: e.message for e in res.errors}


def test_valid_input_parses() -> None:
    res = validate_applicant(GOOD)
    assert isinstance(res, ApplicantInput)
    assert res.cibil_score == 720


def test_numeric_strings_are_accepted() -> None:
    res = validate_applicant({**GOOD, "cibil_score": "700", "loan_amount": "5000000"})
    assert isinstance(res, ApplicantInput) and res.cibil_score == 700


def test_extra_fields_ignored() -> None:
    res = validate_applicant({**GOOD, "name": "someone", "education": "Graduate"})
    assert isinstance(res, ApplicantInput)
    assert not hasattr(res, "name")


def test_assets_default_to_zero() -> None:
    minimal = {k: GOOD[k] for k in ("cibil_score", "income_annum", "loan_amount", "loan_term")}
    res = validate_applicant(minimal)
    assert isinstance(res, ApplicantInput) and res.bank_asset_value == 0


def test_missing_required_fields() -> None:
    errs = errors_for({"cibil_score": 700})
    assert errs["income_annum"] == "Annual income is required."
    assert errs["loan_amount"] == "Loan amount is required."
    assert errs["loan_term"] == "Loan term (years) is required."


@pytest.mark.parametrize("cibil", [299, 901, -5])
def test_cibil_out_of_range(cibil: int) -> None:
    assert errors_for({**GOOD, "cibil_score": cibil})["cibil_score"] == (
        "CIBIL score must be between 300 and 900."
    )


def test_cibil_must_be_whole_number() -> None:
    assert "whole number" in errors_for({**GOOD, "cibil_score": 700.5})["cibil_score"]


def test_non_numeric_value() -> None:
    assert errors_for({**GOOD, "income_annum": "lots"})["income_annum"] == (
        "Annual income must be a number."
    )


@pytest.mark.parametrize("field", ["income_annum", "loan_amount"])
def test_zero_or_negative_amounts_rejected(field: str) -> None:
    assert errors_for({**GOOD, field: 0})[field].endswith("must be greater than 0.")
    assert field in errors_for({**GOOD, field: -1})


def test_negative_asset_rejected() -> None:
    msg = errors_for({**GOOD, "bank_asset_value": -10})["bank_asset_value"]
    assert msg == "Bank assets value must be at least 0."


def test_zero_term_rejected() -> None:
    assert (
        errors_for({**GOOD, "loan_term": 0})["loan_term"] == "Loan term (years) must be at least 1."
    )


@pytest.mark.parametrize("bad", [math.inf, math.nan])
def test_non_finite_rejected(bad: float) -> None:
    assert "loan_amount" in errors_for({**GOOD, "loan_amount": bad})


def test_non_mapping_input() -> None:
    res = validate_applicant(42)
    assert isinstance(res, ValidationFailure)
    assert res.errors[0].message == "Application details are missing."


def test_messages_are_plain_english() -> None:
    errs = errors_for({"cibil_score": "x", "income_annum": -1, "loan_term": 0})
    for msg in errs.values():
        assert msg[0].isupper() and msg.endswith(".")
        assert "pydantic" not in msg.lower() and "Input should" not in msg
