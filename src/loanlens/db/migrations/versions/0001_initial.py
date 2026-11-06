"""Initial schema: anonymised batch summaries (and optional per-row IDs).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-06

The tables match the original ``sqlite3`` schema. Local databases created before Alembic
already have them, so each table is created only if it does not exist yet.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    if op.get_context().as_sql:  # offline mode (--sql): nothing to inspect, emit everything
        return False
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    """Create ``batch_summaries`` and ``batch_rows`` if they are missing."""
    if not _has_table("batch_summaries"):
        op.create_table(
            "batch_summaries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("model_version", sa.String(64), nullable=False),
            sa.Column("total_rows", sa.Integer(), nullable=False),
            sa.Column("valid_rows", sa.Integer(), nullable=False),
            sa.Column("invalid_rows", sa.Integer(), nullable=False),
            sa.Column("approved", sa.Integer(), nullable=False),
            sa.Column("rejected", sa.Integer(), nullable=False),
            sa.Column("borderline", sa.Integer(), nullable=False),
            sa.Column("approval_rate", sa.Float(), nullable=True),
            sa.Column("likelihood_bands", sa.Text(), nullable=False),
            sa.Column("top_rejection_reasons", sa.Text(), nullable=False),
        )
    if not _has_table("batch_rows"):
        op.create_table(
            "batch_rows",
            sa.Column(
                "batch_id", sa.Integer(), sa.ForeignKey("batch_summaries.id"), nullable=False
            ),
            sa.Column("applicant_id", sa.String(200), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("probability", sa.Float(), nullable=False),
        )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("batch_rows")
    op.drop_table("batch_summaries")
