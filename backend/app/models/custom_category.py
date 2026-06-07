"""custom_cost_categories table (CR-001-D).

Company-defined cost categories that supplement the 15 standard ones. Unique
per company by a normalised name; usage_count drives ordering in the cost form.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import GUID as PGUUID


class CustomCostCategory(Base):
    __tablename__ = "custom_cost_categories"
    __table_args__ = (
        UniqueConstraint("company_id", "name_normalized", name="uq_custom_cat_company_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
