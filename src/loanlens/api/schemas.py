"""Request and response models for the REST API.

Applicant fields reuse :class:`loanlens.schema.ApplicantInput` and score responses extend
:class:`loanlens.schema.DecisionResult`, the same models the Streamlit app uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from loanlens.schema import ApplicantInput, DecisionResult


class Credentials(BaseModel):
    """Email and password for sign-in or registration."""

    email: str = Field(max_length=254, examples=["applicant@example.com"])
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    """The signed-in account (no password hash, no internal id)."""

    email: str
    role: Literal["applicant", "manager"]
    must_change_password: bool


class TokenResponse(BaseModel):
    """A bearer token for ``Authorization: Bearer <access_token>``."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


class ScoreRequest(ApplicantInput):
    """The applicant fields plus an optional loan type (``personal`` when omitted)."""

    product: str | None = Field(
        default=None, max_length=32, description="Loan type: personal, home or vehicle"
    )


class ScoreResponse(DecisionResult):
    """A decision plus its display band and the identifiers of the request and audit row."""

    likelihood_band: str = Field(description="Very likely, Likely, Borderline, ...")
    likelihood: str = Field(description="Display text, never 0% or 100%, e.g. '96% - Very likely'")
    request_id: str
    audit_id: str


class BatchResponse(BaseModel):
    """Decisions for a list of applicants, in the order given."""

    batch_id: str
    request_id: str
    count: int
    results: list[ScoreResponse]


class PolicySummary(BaseModel):
    """One policy profile (loan type)."""

    profile: str
    version: str
    description: str
    policy_hash: str


class ModelInfo(BaseModel):
    """The active registered model."""

    version: str
    created_at: str
    kind: str
    calibration: str
    features: list[str]
    cv_metrics: dict[str, float]
    artifact_sha256: str
    training_data_hash: str
    n_train: int


class AuditItem(BaseModel):
    """One audit record (model inputs only; ``user_ref`` is a random account reference)."""

    id: str
    created_at: datetime
    user_ref: str | None
    actor_role: str | None
    channel: Literal["ui", "api", "batch"]
    batch_id: str | None
    request_id: str
    profile: str
    policy_version: str
    policy_hash: str
    model_version: str
    inputs: dict[str, Any]
    status: Literal["Approved", "Rejected"]
    probability: float
    borderline: bool
    reason_codes: list[str]


class AuditResponse(BaseModel):
    """One page of the audit trail."""

    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    items: list[AuditItem]


class ErrorDetail(BaseModel):
    """What went wrong (validation details name fields but never echo the input)."""

    code: str
    message: str
    request_id: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    """Every error has this shape."""

    error: ErrorDetail


class BatchJobOut(BaseModel):
    """A background batch job. File locations are never exposed; use the download links."""

    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "expired"]
    filename: str = Field(description="The uploaded file's name (display only)")
    profile: str
    include_positive: bool
    input_format: Literal["csv", "parquet"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    rows_total: int | None = Field(description="Data rows (estimated until the job finishes)")
    rows_processed: int
    rows_skipped: int
    rows_audited: int
    approved: int
    rejected: int
    borderline: int
    progress: float = Field(ge=0, le=1)
    error_message: str | None
    audit_batch_id: str | None
    audited: bool
    cancel_requested: bool
    summary: dict[str, Any] | None
    result_url: str | None = None
    result_csv_url: str | None = None
    errors_url: str | None = None


class BatchJobList(BaseModel):
    """Recent batch jobs, newest first."""

    count: int
    items: list[BatchJobOut]
