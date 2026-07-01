"""project_milestones table — weighted schedule milestones (CR-019-A).

A queryable child of ``projects`` that adds the **schedule/time dimension** the
finance data lacks: each row is a weighted milestone, optionally grouped under a
``stage`` label (v1 models "stages" as a grouping label, not a separate table).
The weighted rollup gives an objective schedule-progress %.

**SEPARATE LANES (CR-019 §0.2):** milestones are the SCHEDULE lane ONLY. They
drive progress/deadline indicators and must NEVER touch billing, hakediş, margin,
or any forecast/monetary figure. Additive: existing projects simply have no rows.
Company-scoped + RLS, indexed on ``(company_id, project_id)``.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class ProjectMilestone(TimestampSoftDeleteMixin, Base):
    __tablename__ = "project_milestones"
    __table_args__ = (
        # Composite index per CR-019 §0.0.3 / §1.1.
        Index("ix_project_milestones_company_project", "company_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Grouping label (e.g. "Kaba İnşaat", "İnce İşçilik"); NULL = ungrouped.
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The deadline.
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Relative weight for the weighted rollup; unset/zero treated as 1 in SQL.
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("1"), server_default="1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project"] = relationship("Project")  # noqa: F821
