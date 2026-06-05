"""equipment_log table (Section 2.3.1)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin


class EquipmentLog(TimestampSoftDeleteMixin, Base):
    __tablename__ = "equipment_log"

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)

    equipment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ownership_type: Mapped[str] = mapped_column(String(10), nullable=False)  # owned, rented
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_try: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    rate_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)  # day, month
    deployment_start: Mapped[date] = mapped_column(Date, nullable=False)
    deployment_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    fuel_maintenance_try: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
