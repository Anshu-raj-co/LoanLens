"""Decision audit trail: building, writing and reading append-only records (internal).

Pages and the API do not call this module directly; they go through
:mod:`loanlens.services`, which checks the signed-in user's role first.

There is deliberately no function that updates or deletes a record, and database triggers
(Alembic revision ``0003_audit``) reject UPDATE and DELETE on ``decision_audit``.
Records hold the model input fields only, never an email address or name; ``user_ref`` is
the account's random audit reference.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import case, func, insert, select

from loanlens.db.engine import session_scope
from loanlens.db.models import DecisionAudit
from loanlens.decision import INPUT_COLUMNS
from loanlens.schema import DecisionResult

UI, API, BATCH = "ui", "api", "batch"
CHANNELS = (UI, API, BATCH)
CHUNK_SIZE = 1000
INTEGER_INPUTS = {"cibil_score", "loan_term"}
COLUMNS = (
    "id", "created_at", "user_ref", "actor_role", "channel", "batch_id", "request_id",
    "profile", "policy_version", "policy_hash", "model_version", "inputs", "status",
    "probability", "borderline", "reason_codes",
)  # fmt: skip


class AuditFilters(BaseModel):
    """Filters for reading the audit trail (all optional; dates are inclusive, UTC)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    status: Literal["Approved", "Rejected"] | None = None
    profile: str | None = Field(default=None, max_length=32)
    channel: Literal["ui", "api", "batch"] | None = None
    model_version: str | None = Field(default=None, max_length=64)
    policy_version: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _dates_in_order(self) -> AuditFilters:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("The start date must not be after the end date.")
        return self


def new_id() -> str:
    """A new random identifier (UUID4)."""
    return str(uuid.uuid4())


def model_inputs(values: Mapping[str, Any]) -> dict[str, int | float]:
    """Only the model input fields, as plain JSON numbers."""
    out: dict[str, int | float] = {}
    for name in INPUT_COLUMNS:
        value = values[name]
        out[name] = int(value) if name in INTEGER_INPUTS else float(value)
    return out


def build_row(
    *,
    inputs: Mapping[str, Any],
    status: str,
    probability: float,
    borderline: bool,
    reason_codes: Iterable[str],
    profile: str,
    policy_version: str,
    policy_hash: str,
    model_version: str,
    channel: str,
    request_id: str,
    user_ref: str | None,
    actor_role: str | None,
    batch_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """One audit record as a dict (validated channel, model inputs only)."""
    if channel not in CHANNELS:
        raise ValueError(f"Unknown channel {channel!r}.")
    return {
        "id": new_id(),
        "created_at": created_at or datetime.now(UTC),
        "user_ref": user_ref,
        "actor_role": actor_role,
        "channel": channel,
        "batch_id": batch_id,
        "request_id": request_id,
        "profile": profile,
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "model_version": str(model_version),
        "inputs": model_inputs(inputs),
        "status": status,
        "probability": float(probability),
        "borderline": bool(borderline),
        "reason_codes": [str(c) for c in reason_codes if c],
    }


def row_from_result(result: DecisionResult, inputs: Mapping[str, Any], **context: Any) -> dict:
    """An audit record for a :class:`DecisionResult` (``context``: channel, ids, user)."""
    return build_row(
        inputs=inputs, status=result.status, probability=result.probability,
        borderline=result.borderline, reason_codes=[r.code for r in result.reasons],
        profile=result.profile, policy_version=result.policy_version,
        policy_hash=result.policy_hash, model_version=result.model_version, **context,
    )  # fmt: skip


def batch_rows(
    values: Any,
    results: Any,
    *,
    model_version: str,
    request_id: str,
    batch_id: str,
    user_ref: str,
    actor_role: str,
    policies: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Audit records for scored batch rows.

    ``values`` holds the validated model inputs and ``results`` the matching rows of
    :func:`loanlens.batch.score` (same order). ``policies`` caches loaded profiles by name.
    """
    from loanlens.config import load_profile

    policies = {} if policies is None else policies
    inputs = values[list(INPUT_COLUMNS)].to_dict("records")
    rows = []
    for vals, status, probability, borderline, product, codes in zip(
        inputs, results["status"], results["probability"], results["borderline"],
        results["product"], results["reason_codes"], strict=True,
    ):  # fmt: skip
        prof = policies.get(product) or policies.setdefault(product, load_profile(product))
        rows.append(
            build_row(
                inputs=vals,
                status=status,
                probability=float(probability),
                borderline=bool(borderline),
                reason_codes=str(codes or "").split(";"),
                profile=prof.profile,
                policy_version=prof.version,
                policy_hash=prof.content_hash,
                model_version=model_version,
                channel=BATCH,
                request_id=request_id,
                batch_id=batch_id,
                user_ref=user_ref,
                actor_role=actor_role,
            )  # fmt: skip
        )
    return rows


def write(url: str, rows: Sequence[dict[str, Any]], chunk_size: int = CHUNK_SIZE) -> int:
    """Insert ``rows`` in chunks (one transaction per chunk); returns the number written."""
    for start in range(0, len(rows), chunk_size):
        with session_scope(url) as session:
            session.execute(insert(DecisionAudit), list(rows[start : start + chunk_size]))
    return len(rows)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _conditions(filters: AuditFilters, user_ref: str | None) -> list:
    table = DecisionAudit
    conds = []
    if user_ref is not None:
        conds.append(table.user_ref == user_ref)
    if filters.date_from:
        conds.append(table.created_at >= datetime.combine(filters.date_from, time.min, UTC))
    if filters.date_to:
        end = datetime.combine(filters.date_to + timedelta(days=1), time.min, UTC)
        conds.append(table.created_at < end)
    for name in ("status", "profile", "channel", "model_version", "policy_version"):
        value = getattr(filters, name)
        if value:
            conds.append(getattr(table, name) == value)
    return conds


def _as_dict(record: DecisionAudit) -> dict[str, Any]:
    row = {name: getattr(record, name) for name in COLUMNS}
    row["created_at"] = _aware(row["created_at"])
    return row


def query(
    url: str,
    filters: AuditFilters | None = None,
    *,
    user_ref: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Matching records, newest first, plus the total number that match."""
    conds = _conditions(filters or AuditFilters(), user_ref)
    with session_scope(url) as session:
        total = session.execute(
            select(func.count()).select_from(DecisionAudit).where(*conds)
        ).scalar_one()
        records = session.execute(
            select(DecisionAudit).where(*conds)
            .order_by(DecisionAudit.created_at.desc(), DecisionAudit.id)
            .limit(limit).offset(offset)
        ).scalars().all()  # fmt: skip
        return [_as_dict(r) for r in records], int(total)


def counts(
    url: str, filters: AuditFilters | None = None, *, user_ref: str | None = None
) -> dict[str, int]:
    """Total, approved, rejected and borderline counts for the matching records."""
    conds = _conditions(filters or AuditFilters(), user_ref)
    table = DecisionAudit
    with session_scope(url) as session:
        total, approved, borderline = session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((table.status == "Approved", 1), else_=0)), 0),
                func.coalesce(func.sum(case((table.borderline.is_(True), 1), else_=0)), 0),
            ).where(*conds)
        ).one()
    total, approved, borderline = int(total), int(approved), int(borderline)
    return {
        "total": total,
        "approved": approved,
        "rejected": total - approved,
        "borderline": borderline,
    }


def options(url: str) -> dict[str, list[str]]:
    """Distinct profiles, model versions and policy versions present in the trail."""
    out: dict[str, list[str]] = {}
    with session_scope(url) as session:
        for name in ("profile", "model_version", "policy_version"):
            column = getattr(DecisionAudit, name)
            values = session.execute(select(column).distinct().order_by(column)).scalars()
            out[name] = [str(v) for v in values]
    return out
