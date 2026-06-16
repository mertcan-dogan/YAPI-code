"""project_units table — the daire dağılımı / unit schedule (CR-016-A).

A queryable child of ``projects`` (one row per unit type, e.g. 12 × 2+1) so the
per-m² metrics CR-017 needs (cost/m², revenue/m², profit/m²) can be aggregated
across comparable projects later — not a free-text JSON blob (§0.2). Additive:
existing projects simply have no rows. Company-scoped + RLS, like every table.
"""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class ProjectUnit(TimestampSoftDeleteMixin, Base):
    __tablename__ = "project_units"
    __table_args__ = (
        Index("ix_project_units_project", "project_id"),
        Index("ix_project_units_company", "company_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Preset key from UNIT_TYPES (1+1 … other); custom_label set when "other".
    unit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    custom_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    gross_m2_each: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    net_m2_each: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Optional; strengthens CR-017 revenue/m².
    sale_price_try: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Parent project (the Project.units side is view-only; see project.py).
    project: Mapped["Project"] = relationship("Project")  # noqa: F821
