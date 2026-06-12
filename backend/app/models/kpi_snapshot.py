"""kpi_snapshots table — daily company-level KPI history for dashboard sparklines/deltas.

One row per (company_id, snapshot_date). Written (upserted) when the company
dashboard is loaded, so trend series and month-over-month deltas are based on
real recorded history rather than fabricated values.
"""
import uuid
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class KPISnapshot(TimestampSoftDeleteMixin, Base):
    __tablename__ = "kpi_snapshots"
    __table_args__ = (
        UniqueConstraint("company_id", "snapshot_date", name="uq_kpi_snapshot_company_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    snapshot_date: Mapped[date_type] = mapped_column(Date, nullable=False)

    active_project_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_contract_value_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    weighted_avg_margin_pct: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    overdue_payment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
