"""Background batch jobs and worker heartbeats.

Revision ID: 0004_batch_jobs
Revises: 0003_audit
Create Date: 2026-11-06

* ``batch_jobs``: one row per uploaded Bulk Check file. The upload and the result files live
  in a private directory under random names; this table stores only those names, never a
  path from the client. ``created_by`` is the submitting manager's ``audit_ref``.
* ``batch_workers``: a heartbeat per running worker, so the app can tell whether an external
  worker is running before it starts its embedded one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_batch_jobs"
down_revision = "0003_audit"
branch_labels = None
depends_on = None

STATUSES = "('queued', 'running', 'completed', 'failed', 'cancelled', 'expired')"


def upgrade() -> None:
    """Create ``batch_jobs`` and ``batch_workers``."""
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("include_positive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_format", sa.String(8), nullable=False),
        sa.Column("upload_path", sa.String(64), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_audited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("borderline", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_path", sa.String(64), nullable=True),
        sa.Column("result_csv_path", sa.String(64), nullable=True),
        sa.Column("errors_path", sa.String(64), nullable=True),
        sa.Column("audit_batch_id", sa.String(36), nullable=True),
        sa.Column("audited", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_batch_jobs_status"),
    )
    op.create_index("ix_batch_jobs_status_created", "batch_jobs", ["status", "created_at"])
    op.create_index("ix_batch_jobs_created_by", "batch_jobs", ["created_by"])
    op.create_index("ix_batch_jobs_claim_token", "batch_jobs", ["claim_token"])
    op.create_table(
        "batch_workers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('external', 'embedded')", name="ck_batch_workers_kind"),
    )


def downgrade() -> None:
    """Drop the job and worker tables."""
    op.drop_table("batch_workers")
    op.drop_table("batch_jobs")
