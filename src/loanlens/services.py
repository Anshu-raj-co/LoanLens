"""The protected service layer: the only functions the Streamlit pages and the API call.

Every function that scores applicants, runs a batch, reads analytics or batch summaries,
or reads or writes the audit trail takes the signed-in :class:`~loanlens.auth.Principal`
and checks it itself through :func:`loanlens.auth.verify_principal`:

* no principal, a principal that was not issued by a sign-in (a hand-built one), or one
  that is stale (password or status changed, account deactivated or deleted) raises
  :class:`~loanlens.auth.InvalidSession`;
* a role that does not allow the action raises :class:`~loanlens.auth.PermissionDenied`.

Both are :class:`~loanlens.auth.AuthorisationError`. Applicants may score their own
applications and read only their own history; batches, analytics, batch summaries and the
full audit trail are for managers.

Every decision is written to the append-only audit trail before it is returned. If the
record cannot be written, the decision is not returned either (the error is raised).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from loanlens import audit, batch, cleaning, explain, storage
from loanlens import model as model_mod
from loanlens.audit import API, BATCH, UI, AuditFilters
from loanlens.auth import APPLICANT, MANAGER, Principal, verify_principal
from loanlens.config import DEFAULT_PROFILE, Policy, load_profile, normalise_profile
from loanlens.decision import INPUT_COLUMNS, decide_many
from loanlens.schema import ApplicantInput, DecisionResult, ValidationFailure, validate_applicant

__all__ = [
    "API",
    "BATCH",
    "UI",
    "AuditFilters",
    "AuditPage",
    "BatchRun",
    "InvalidRecords",
    "Scored",
    "ScoredMany",
    "audit_export",
    "audit_filter_options",
    "audit_records",
    "feature_importance",
    "latest_batch_summary",
    "my_history",
    "new_request_id",
    "recent_batch_summaries",
    "save_batch_summary",
    "score_applicant",
    "score_batch_upload",
    "score_records",
    "training_data",
]

EXPORT_LIMIT = 100_000
MAX_PAGE_SIZE = 500


class InvalidRecords(ValueError):
    """Some records in a list are invalid; ``errors`` maps the list index to the problems."""

    def __init__(self, errors: dict[int, ValidationFailure]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} record(s) are not valid.")


@dataclass(frozen=True)
class Scored:
    """One audited decision."""

    result: DecisionResult
    audit_id: str
    request_id: str


@dataclass(frozen=True)
class ScoredMany:
    """Audited decisions for a list of applicants (same order as given)."""

    results: list[DecisionResult]
    audit_ids: list[str]
    batch_id: str
    request_id: str


@dataclass(frozen=True)
class BatchRun:
    """An audited Bulk Check upload."""

    results: pd.DataFrame
    batch_id: str
    request_id: str


@dataclass(frozen=True)
class AuditPage:
    """One page of audit records with the total and the counts for the whole filter."""

    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


def new_request_id() -> str:
    """A new request identifier (also used for UI decisions, which have no HTTP request)."""
    return uuid.uuid4().hex


def _url(policy: Policy | None = None) -> str:
    return storage.resolve_url(policy=policy)


def _inputs(applicant: ApplicantInput) -> dict[str, Any]:
    return {name: getattr(applicant, name) for name in INPUT_COLUMNS}


def _channel(channel: str, allowed: Sequence[str]) -> str:
    if channel not in allowed:
        raise ValueError(f"Channel must be one of {', '.join(allowed)}.")
    return channel


# ---- Scoring ---------------------------------------------------------------------------------


def score_applicant(
    principal: Principal | None,
    data: Mapping[str, Any] | ApplicantInput,
    *,
    product: str | None = None,
    channel: str = UI,
    request_id: str | None = None,
    artifact: dict[str, Any] | None = None,
) -> Scored | ValidationFailure:
    """Score one application for any signed-in user and write its audit record.

    Returns a :class:`ValidationFailure` (and writes nothing) when the input is invalid.

    Raises:
        AuthorisationError: no valid signed-in principal.
        UnknownProfileError: ``product`` names no loan type.
        DatabaseError: the audit record could not be written (no decision is returned).
    """
    who = verify_principal(principal, APPLICANT, MANAGER)
    _channel(channel, (UI, API))
    policy = load_profile(product or DEFAULT_PROFILE)
    applicant = validate_applicant(_inputs(data) if isinstance(data, ApplicantInput) else data)
    if isinstance(applicant, ValidationFailure):
        return applicant
    values = pd.DataFrame([applicant.model_dump()])
    result = decide_many(values, policy, artifact)[0]
    rid = request_id or new_request_id()
    row = audit.row_from_result(
        result, _inputs(applicant), channel=channel, request_id=rid,
        user_ref=who.audit_ref, actor_role=who.role,
    )  # fmt: skip
    audit.write(_url(), [row])
    return Scored(result=result, audit_id=row["id"], request_id=rid)


def score_records(
    principal: Principal | None,
    records: Sequence[Mapping[str, Any] | ApplicantInput],
    *,
    products: Sequence[str | None] | None = None,
    channel: str = API,
    request_id: str | None = None,
    artifact: dict[str, Any] | None = None,
) -> ScoredMany:
    """Score a list of applicants (managers only) and audit every decision.

    Each record is decided exactly as :func:`score_applicant` would decide it, under its own
    loan type. The audit rows share one ``batch_id`` and are inserted in chunks.

    Raises:
        AuthorisationError: no valid principal, or not a manager.
        InvalidRecords: one or more records are invalid (nothing is scored or written).
        UnknownProfileError: a product names no loan type.
    """
    who = verify_principal(principal, MANAGER)
    _channel(channel, (API, BATCH))
    products = list(products) if products is not None else [None] * len(records)
    if len(products) != len(records):
        raise ValueError("products must have one entry per record.")
    names = [normalise_profile(p) if p else DEFAULT_PROFILE for p in products]
    policies = {name: load_profile(name) for name in dict.fromkeys(names)}
    applicants: list[ApplicantInput] = []
    errors: dict[int, ValidationFailure] = {}
    for i, record in enumerate(records):
        parsed = validate_applicant(
            _inputs(record) if isinstance(record, ApplicantInput) else record
        )
        if isinstance(parsed, ValidationFailure):
            errors[i] = parsed
        else:
            applicants.append(parsed)
    if errors:
        raise InvalidRecords(errors)
    artifact = artifact or model_mod.load_artifact()
    results: list[DecisionResult | None] = [None] * len(applicants)
    for name, policy in policies.items():
        idx = [i for i, n in enumerate(names) if n == name]
        frame = pd.DataFrame([applicants[i].model_dump() for i in idx])
        for i, res in zip(idx, decide_many(frame, policy, artifact), strict=True):
            results[i] = res
    rid = request_id or new_request_id()
    batch_id = audit.new_id()
    rows = [
        audit.row_from_result(
            res,
            _inputs(app),
            channel=channel,
            request_id=rid,
            batch_id=batch_id,
            user_ref=who.audit_ref,
            actor_role=who.role,
        )  # fmt: skip
        for res, app in zip(results, applicants, strict=True)
    ]
    audit.write(_url(), rows)
    return ScoredMany(
        results=list(results), audit_ids=[r["id"] for r in rows], batch_id=batch_id,
        request_id=rid,
    )  # fmt: skip


def score_batch_upload(
    principal: Principal | None,
    parsed: batch.ParsedBatch,
    policy: Policy | None = None,
    *,
    artifact: dict[str, Any] | None = None,
    include_positive: bool = False,
    progress: Callable[[float], None] | None = None,
) -> BatchRun:
    """Score a parsed Bulk Check upload (managers only) and audit every row in chunks.

    Raises:
        AuthorisationError: no valid principal, or not a manager.
        DatabaseError: the audit records could not be written (results are not returned).
    """
    who = verify_principal(principal, MANAGER)
    artifact = artifact or model_mod.load_artifact()
    results = batch.score(
        parsed, policy, artifact, include_positive=include_positive, progress=progress
    )
    rid, batch_id = new_request_id(), audit.new_id()
    model_version = str(artifact.get("version", "unknown"))
    inputs = parsed.values[list(INPUT_COLUMNS)].to_dict("records")
    profiles: dict[str, Policy] = {}
    rows = []
    for values, status, probability, borderline, product, codes in zip(
        inputs,
        results["status"],
        results["probability"],
        results["borderline"],
        results[batch.PRODUCT_COLUMN],
        results["reason_codes"],
        strict=True,
    ):
        prof = profiles.get(product) or profiles.setdefault(product, load_profile(product))
        rows.append(
            audit.build_row(
                inputs=values,
                status=status,
                probability=float(probability),
                borderline=bool(borderline),
                reason_codes=str(codes or "").split(";"),
                profile=prof.profile,
                policy_version=prof.version,
                policy_hash=prof.content_hash,
                model_version=model_version,
                channel=BATCH,
                request_id=rid,
                batch_id=batch_id,
                user_ref=who.audit_ref,
                actor_role=who.role,
            )  # fmt: skip
        )
    audit.write(_url(policy), rows)
    return BatchRun(results=results, batch_id=batch_id, request_id=rid)


# ---- Batch summaries and analytics (managers) ------------------------------------------------


def save_batch_summary(
    principal: Principal | None,
    summary: dict[str, Any],
    model_version: str,
    results: pd.DataFrame | None = None,
    policy: Policy | None = None,
) -> int:
    """Store the anonymised summary of a batch (managers only); returns its id."""
    verify_principal(principal, MANAGER)
    return storage.save_summary(summary, model_version, results, policy)


def latest_batch_summary(
    principal: Principal | None, policy: Policy | None = None
) -> dict[str, Any] | None:
    """The most recent batch summary (managers only)."""
    verify_principal(principal, MANAGER)
    return storage.latest_summary(url=_url(policy))


def recent_batch_summaries(
    principal: Principal | None, limit: int = 10, policy: Policy | None = None
) -> pd.DataFrame:
    """Recent batch summaries, newest first (managers only)."""
    verify_principal(principal, MANAGER)
    return storage.list_summaries(limit, url=_url(policy))


@lru_cache(maxsize=2)
def _training_data(path: str, mtime: float) -> pd.DataFrame:  # noqa: ARG001 - cache key
    return pd.read_csv(path)


def training_data(principal: Principal | None) -> pd.DataFrame | None:
    """The cleaned synthetic training data for the Analytics charts (managers only)."""
    verify_principal(principal, MANAGER)
    path = Path(cleaning.PROCESSED_PATH)
    if not path.exists():
        return None
    return _training_data(str(path), path.stat().st_mtime).copy()


_importance: dict[tuple[str, str, float], pd.Series] = {}


def feature_importance(principal: Principal | None, artifact: dict[str, Any]) -> pd.Series | None:
    """Mean absolute SHAP share per feature on the training data (managers only)."""
    verify_principal(principal, MANAGER)
    path = Path(cleaning.PROCESSED_PATH)
    if not path.exists():
        return None
    key = (str(artifact.get("version")), str(artifact.get("trained_at")), path.stat().st_mtime)
    if key not in _importance:
        frame = _training_data(str(path), path.stat().st_mtime)
        _importance[key] = explain.feature_importance(artifact, model_mod.build_frame(frame))
    return _importance[key].copy()


# ---- Audit trail -----------------------------------------------------------------------------


def my_history(principal: Principal | None, limit: int = 1000) -> list[dict[str, Any]]:
    """The signed-in user's own decisions, newest first. Never anyone else's."""
    who = verify_principal(principal, APPLICANT, MANAGER)
    items, _ = audit.query(_url(), AuditFilters(), user_ref=who.audit_ref, limit=limit)
    return items


def audit_records(
    principal: Principal | None,
    filters: AuditFilters | None = None,
    *,
    page: int = 1,
    page_size: int = 50,
) -> AuditPage:
    """One page of the full audit trail with counts for the filter (managers only)."""
    verify_principal(principal, MANAGER)
    page = max(1, int(page))
    page_size = int(np.clip(page_size, 1, MAX_PAGE_SIZE))
    filters = filters or AuditFilters()
    url = _url()
    items, total = audit.query(url, filters, limit=page_size, offset=(page - 1) * page_size)
    return AuditPage(
        items=items, total=total, page=page, page_size=page_size,
        counts=audit.counts(url, filters),
    )  # fmt: skip


def audit_export(
    principal: Principal | None, filters: AuditFilters | None = None, limit: int = EXPORT_LIMIT
) -> list[dict[str, Any]]:
    """Every matching audit record up to ``limit`` (managers only), for CSV export."""
    verify_principal(principal, MANAGER)
    items, _ = audit.query(_url(), filters, limit=limit)
    return items


def audit_filter_options(principal: Principal | None) -> dict[str, list[str]]:
    """Values present in the trail for the profile and version filters (managers only)."""
    verify_principal(principal, MANAGER)
    return audit.options(_url())
