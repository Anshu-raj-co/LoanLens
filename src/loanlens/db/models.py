"""Database tables. Only anonymised Bulk Check summaries are stored.

``batch_summaries`` holds aggregate counts per batch: no names, no applicant IDs and no
input values. ``batch_rows`` (applicant ID, status, probability) is written only when
``storage.store_applicant_ids`` is enabled in the policy file. The columns match the
original ``sqlite3`` schema exactly, so existing local databases keep working.
"""

from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Table, Text
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
