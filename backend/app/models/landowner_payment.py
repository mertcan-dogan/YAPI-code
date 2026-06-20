"""landowner_payments table — arsa sahibi ödeme defteri (CR-031-B).

The landowner-contribution ledger for share revenue models (kat karşılığı /
hasılat paylaşımı): one row per payment made to / contribution from the
landowner side. FX-at-date per CR-014 (amount_try + rate@payment_date →
amount_usd). Part of sell-side revenue (§0.2) — NEVER feeds hakediş revenue.
Company-scoped + RLS + composite ``(company_id, project_id)`` index.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class LandownerPayment(TimestampSoftDeleteMixin, Base):
    __tablename__ = "landowner_payments"
    __table_args__ = (
        Index("ix_landowner_payments_company_project", "company_id", "project_id"),
        Index("ix_landowner_payments_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )

    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Header-level commitment (taahhüt edilen katkı); may repeat across rows.
    committed_total_try: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # CR-014 pattern: rate at payment_date + derived USD (TRY ÷ rate). Auto-filled.
    fx_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    payment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
