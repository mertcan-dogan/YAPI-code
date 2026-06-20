"""unit_sales table — the daire satış kaydı / sales register (CR-031-A).

The sell-side revenue lane the cost spine has lacked. One row per sale of a unit
(daire/dükkan/ofis) for developer/seller revenue models (kat karşılığı, yap-sat,
hasılat paylaşımı). FX-at-date per CR-014: ``sale_price_try`` + the rate at the
sale's own date → derived ``sale_price_usd``. Per-unit cost is an *allocation
view* computed at read-time (calculations/pnl.py) — this table never stores a
cost. Company-scoped + RLS + composite ``(company_id, project_id)`` index.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class UnitSale(TimestampSoftDeleteMixin, Base):
    __tablename__ = "unit_sales"
    __table_args__ = (
        Index("ix_unit_sales_company_project", "company_id", "project_id"),
        Index("ix_unit_sales_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Optional link to a scheduled unit (CR-016); a sale may also be free-text.
    project_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("project_units.id"), nullable=True
    )

    unit_label: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    floor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gross_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    net_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sale_price_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    # CR-014 pattern: rate at sale_date + derived USD (TRY ÷ rate). Auto-filled.
    fx_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    sale_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    payment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    installment_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deed_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Which side's unit was sold (the workbook's Yüklenici Payı / Arsa Sahibi Payı).
    owner_side: Mapped[str] = mapped_column(
        String(20), nullable=False, default="yuklenici", server_default="yuklenici"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
