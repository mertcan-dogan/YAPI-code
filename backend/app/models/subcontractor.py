"""subcontractors table (Section 2.3.1)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin


class Subcontractor(TimestampSoftDeleteMixin, Base):
    __tablename__ = "subcontractors"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_of_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_value_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    approved_variations_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    retention_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"), server_default="10.00")
    contract_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
