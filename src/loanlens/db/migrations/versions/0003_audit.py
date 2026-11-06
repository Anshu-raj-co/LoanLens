"""Append-only decision audit trail and session invalidation.

Revision ID: 0003_audit
Revises: 0002_auth
Create Date: 2026-11-06

* ``decision_audit``: one row per decision (UI, API or batch). Database triggers reject
  every UPDATE and DELETE on SQLite and PostgreSQL (and TRUNCATE on PostgreSQL).
* ``users.token_version``: session tokens carry it; raising it invalidates older tokens.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_audit"
down_revision = "0002_auth"
branch_labels = None
depends_on = None

APPEND_ONLY = "decision_audit is append-only: records cannot be changed or deleted"

SQLITE_TRIGGERS = (
    f"""CREATE TRIGGER decision_audit_no_update BEFORE UPDATE ON decision_audit
    BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY}'); END""",
    f"""CREATE TRIGGER decision_audit_no_delete BEFORE DELETE ON decision_audit
    BEGIN SELECT RAISE(ABORT, '{APPEND_ONLY}'); END""",
)
POSTGRES_TRIGGERS = (
    f"""CREATE OR REPLACE FUNCTION decision_audit_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION '{APPEND_ONLY}'; END $$""",
    """CREATE TRIGGER decision_audit_no_update_delete BEFORE UPDATE OR DELETE ON decision_audit
    FOR EACH ROW EXECUTE FUNCTION decision_audit_append_only()""",
    """CREATE TRIGGER decision_audit_no_truncate BEFORE TRUNCATE ON decision_audit
    FOR EACH STATEMENT EXECUTE FUNCTION decision_audit_append_only()""",
)


def upgrade() -> None:
    """Add ``users.token_version`` and the append-only ``decision_audit`` table."""
    # A plain ADD COLUMN (no table copy), so existing rows and foreign keys are untouched.
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "decision_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_ref", sa.String(36), nullable=True),
        sa.Column("actor_role", sa.String(16), nullable=True),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("borderline", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.CheckConstraint("channel IN ('ui', 'api', 'batch')", name="ck_decision_audit_channel"),
    )
    op.create_index("ix_decision_audit_created_at", "decision_audit", ["created_at"])
    op.create_index("ix_decision_audit_user_ref", "decision_audit", ["user_ref"])
    op.create_index("ix_decision_audit_batch_id", "decision_audit", ["batch_id"])
    dialect = op.get_context().dialect.name
    statements = POSTGRES_TRIGGERS if dialect == "postgresql" else SQLITE_TRIGGERS
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    """Drop the audit table (and its triggers) and ``users.token_version``."""
    op.drop_table("decision_audit")  # triggers go with the table
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS decision_audit_append_only()")
    op.drop_column("users", "token_version")
