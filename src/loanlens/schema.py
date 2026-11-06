"""Pydantic models for applicant input and decision output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from loanlens.rules import RuleResult

FIELD_LABELS: dict[str, str] = {
    "cibil_score": "CIBIL score",
    "income_annum": "Annual income",
    "loan_amount": "Loan amount",
    "loan_term": "Loan term (years)",
    "residential_assets_value": "Residential assets value",
    "commercial_assets_value": "Commercial assets value",
    "luxury_assets_value": "Luxury assets value",
    "bank_asset_value": "Bank assets value",
}


class ApplicantInput(BaseModel):
    """One loan application. Amounts in INR, term in whole years.

    Only the fields the decision needs are accepted; unknown fields are ignored.
    """

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, frozen=True)

    cibil_score: int = Field(ge=300, le=900, description="CIBIL score, 300 to 900")
    income_annum: float = Field(gt=0, description="Annual income in INR")
    loan_amount: float = Field(gt=0, description="Requested loan amount in INR")
    loan_term: int = Field(ge=1, le=40, description="Loan term in years")
    residential_assets_value: float = Field(default=0, ge=0)
    commercial_assets_value: float = Field(default=0, ge=0)
    luxury_assets_value: float = Field(default=0, ge=0)
    bank_asset_value: float = Field(default=0, ge=0)


class FieldError(BaseModel):
    """A single input problem, in plain English."""

    field: str
    message: str


class ValidationFailure(BaseModel):
    """Returned instead of a decision when the input is invalid. Contains no decision."""

    errors: list[FieldError]


class Reason(BaseModel):
    """A plain-English reason (or positive factor) behind a decision."""

    code: str
    message: str
    your_value: str
    benchmark: str
    suggestion: str
    source: Literal["rule", "model"]
    weight: float = Field(description="Ranking weight; higher means more important")


class Change(BaseModel):
    """One change that would likely flip a rejection to approval."""

    feature: Literal["cibil_score", "loan_amount"]
    current_value: float
    suggested_value: float
    message: str


class DecisionResult(BaseModel):
    """Output of :func:`loanlens.decision.decide` (CLAUDE.md section 5)."""

    status: Literal["Approved", "Rejected"]
    probability: float = Field(ge=0, le=1)
    borderline: bool
    reasons: list[Reason]
    positive_factors: list[Reason]
    what_would_change: list[Change]
    rule_results: list[RuleResult]
    warnings: list[str]
    model_version: str
    profile: str = Field(description="Policy profile (loan type) that was applied")
    policy_version: str = Field(description="Semantic version of that profile")
    policy_hash: str = Field(description="SHA-256 of the profile's validated settings")


def _num(value: object) -> str:
    return f"{value:g}" if isinstance(value, int | float) else str(value)


def _friendly(err: dict) -> FieldError:
    field = str(err["loc"][0]) if err.get("loc") else "input"
    label = FIELD_LABELS.get(field, field)
    ctx = err.get("ctx") or {}
    kind = err["type"]
    if kind == "missing":
        msg = f"{label} is required."
    elif kind in {"int_parsing", "float_parsing", "int_type", "float_type"}:
        msg = f"{label} must be a number."
    elif kind == "int_from_float":
        msg = f"{label} must be a whole number."
    elif kind == "finite_number":
        msg = f"{label} must be a finite number."
    elif kind == "greater_than":
        msg = f"{label} must be greater than {_num(ctx.get('gt'))}."
    elif kind == "greater_than_equal":
        msg = f"{label} must be at least {_num(ctx.get('ge'))}."
    elif kind == "less_than_equal":
        msg = f"{label} must be at most {_num(ctx.get('le'))}."
    else:
        msg = f"{label}: {err.get('msg', 'invalid value')}."
    if field == "cibil_score" and kind in {"greater_than_equal", "less_than_equal"}:
        msg = "CIBIL score must be between 300 and 900."
    return FieldError(field=field, message=msg)


def validate_applicant(data: object) -> ApplicantInput | ValidationFailure:
    """Validate raw input; return the parsed applicant or a list of friendly errors."""
    if isinstance(data, ApplicantInput):
        return data
    if not isinstance(data, dict):
        try:
            data = dict(data)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return ValidationFailure(
                errors=[FieldError(field="input", message="Application details are missing.")]
            )
    try:
        return ApplicantInput.model_validate(data)
    except ValidationError as exc:
        return ValidationFailure(errors=[_friendly(e) for e in exc.errors()])
