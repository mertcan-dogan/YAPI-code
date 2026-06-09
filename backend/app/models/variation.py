"""variations table — change orders / Ek İş (CR-003-I)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Computed, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class Variation(TimestampSoftDeleteMixin, Base):
    __tablename__ = "variations"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    variation_number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_date: Mapped[date] = mapped_column(Date, nullable=False)
    approved_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    value_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    approved_value_try: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_impact_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    # margin impact = approved value (or 0) - cost impact
    margin_impact_try: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        Computed("COALESCE(approved_value_try, 0) - cost_impact_try", persisted=True),
    )
    cost_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
