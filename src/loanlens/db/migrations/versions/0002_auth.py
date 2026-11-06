"""User accounts and sign-in events.

Revision ID: 0002_auth
Revises: 0001_initial
Create Date: 2026-11-06

``users`` holds email (lower-case, unique), an argon2id password hash, role, status,
timestamps, lockout counters and a separate random ``audit_ref``. ``auth_events`` holds
sign-in attempts and account changes with a short reason code, never a password or token.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_auth"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ``users`` and ``auth_events``."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("audit_ref", sa.String(36), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('applicant', 'manager')", name="ck_users_role"),
        sa.UniqueConstraint("audit_ref", name="uq_users_audit_ref"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
    )
    op.create_index("ix_auth_events_user_id", "auth_events", ["user_id"])


def downgrade() -> None:
    """Drop both tables."""
    op.drop_index("ix_auth_events_user_id", table_name="auth_events")
    op.drop_table("auth_events")
    op.drop_table("users")
