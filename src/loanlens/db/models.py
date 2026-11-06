"""Database tables: anonymised Bulk Check summaries, user accounts and sign-in events.

``batch_summaries`` holds aggregate counts per batch: no names, no applicant IDs and no
input values. ``batch_rows`` (applicant ID, status, probability) is written only when
``storage.store_applicant_ids`` is enabled in the policy file. The columns match the
original ``sqlite3`` schema exactly, so existing local databases keep working.

``users`` holds one row per account: email, an argon2id password hash, role, status and
timestamps, plus ``audit_ref``, a separate random UUID for pseudonymous audit records.
``auth_events`` records sign-ins and account changes with a short reason code; it never
holds a password, a token or an email address.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base; ``Base.metadata`` is the target of the Alembic migrations."""


class BatchSummary(Base):
    """One anonymised Bulk Check summary."""

    __tablename__ = "batch_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    approved: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    borderline: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    likelihood_bands: Mapped[str] = mapped_column(Text, nullable=False)
    top_rejection_reasons: Mapped[str] = mapped_column(Text, nullable=False)


# No primary key in the original schema, so this stays a Core table (inserted with
# parameterised statements) rather than an ORM class.
batch_rows = Table(
    "batch_rows",
    Base.metadata,
    Column("batch_id", Integer, ForeignKey("batch_summaries.id"), nullable=False),
    Column("applicant_id", String(200), nullable=True),
    Column("status", String(16), nullable=False),
    Column("probability", Float, nullable=False),
)


class User(Base):
    """One account (applicant or manager). Emails are stored lower-case."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('applicant', 'manager')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_ref: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Raised on a password change, a temporary password or a status change; session tokens
    # carry the value they were issued with, and older tokens are rejected.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuthEvent(Base):
    """A sign-in attempt or account change. Never stores a password, token or email."""

    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set to NULL when the account is deleted, so old events can no longer be linked to it.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64))


JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "expired")


class BatchJob(Base):
    """One background Bulk Check job (Alembic revision ``0004_batch_jobs``).

    ``upload_path``, ``result_path``, ``result_csv_path`` and ``errors_path`` are random file
    names inside the private jobs directory, never a path from the client. ``filename`` is
    the client's file name for display only. ``created_by`` is the submitting manager's
    ``audit_ref``; the worker uses it for the audit rows, so it needs no session token.
    """

    __tablename__ = "batch_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'expired')",
            name="ck_batch_jobs_status",
        ),
        Index("ix_batch_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    include_positive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_format: Mapped[str] = mapped_column(String(8), nullable=False)
    upload_path: Mapped[str | None] = mapped_column(String(64))
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_audited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    borderline: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(64))
    result_csv_path: Mapped[str | None] = mapped_column(String(64))
    errors_path: Mapped[str | None] = mapped_column(String(64))
    audit_batch_id: Mapped[str | None] = mapped_column(String(36))
    audited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    summary: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    claim_token: Mapped[str | None] = mapped_column(String(36), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BatchWorker(Base):
    """A running worker's heartbeat (external process or embedded thread)."""

    __tablename__ = "batch_workers"
    __table_args__ = (
        CheckConstraint("kind IN ('external', 'embedded')", name="ck_batch_workers_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionAudit(Base):
    """One decision, append-only (database triggers reject UPDATE and DELETE).

    ``user_ref`` is the signed-in user's random ``audit_ref``, never an email or name, so
    once the account is deleted the record can no longer be linked to a person. ``inputs``
    holds only the model input fields.
    """

    __tablename__ = "decision_audit"
    __table_args__ = (
        CheckConstraint("channel IN ('ui', 'api', 'batch')", name="ck_decision_audit_channel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    user_ref: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    borderline: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False)
