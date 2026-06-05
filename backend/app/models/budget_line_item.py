"""budget_line_items table — one row per cost_category per project (Section 2.3.1)."""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin


class BudgetLineItem(TimestampSoftDeleteMixin, Base):
    __tablename__ = "budget_line_items"
    __table_args__ = (
        UniqueConstraint("project_id", "cost_category", name="uq_budget_project_category"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    cost_category: Mapped[str] = mapped_column(String(50), nullable=False)
    original_budget_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    approved_variations_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    forecast_final_try: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
