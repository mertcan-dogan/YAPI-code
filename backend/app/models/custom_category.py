"""custom_cost_categories table (CR-001-D; extended in CR-018-A).

Company-defined cost categories that supplement the 15 standard ones, reused for
company-custom *subcategories*. usage_count drives ordering in the cost form.

CR-018-A: ``parent_category`` distinguishes the two roles —
  - NULL              → a top-level custom category (CR-001-D behavior, unchanged);
  - a COST_CATEGORY key → a custom subcategory under that standard category.
Uniqueness is now per (company, parent, normalised name) so the same sub-name can
live under different parents. NOTE: because SQL treats NULLs as distinct, the DB
constraint does not dedup top-level customs (parent NULL) — that dedup is enforced
at the API layer (CR-018-B), matching the original CR-001-D behavior.
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
        UniqueConstraint(
            "company_id", "parent_category", "name_normalized",
            name="uq_custom_cat_company_parent_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    # NULL = top-level custom category; a COST_CATEGORY key = a custom subcategory.
    parent_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
