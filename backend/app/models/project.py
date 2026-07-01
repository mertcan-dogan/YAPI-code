"""projects table (Section 2.3.1)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Text
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampSoftDeleteMixin


class Project(TimestampSoftDeleteMixin, Base):
    __tablename__ = "projects"
    # contract value cannot be zero or negative (Section 8.1)
    __table_args__ = (
        CheckConstraint("contract_value_try > 0", name="ck_projects_contract_value_positive"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    project_code: Mapped[str] = mapped_column(String(50), nullable=False)
    project_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # CR: revenue/billing model — hakedis | kat_karsiligi | yap_sat | hasilat_paylasimi | maliyet_kar
    revenue_model: Mapped[str] = mapped_column(String(30), default="hakedis", server_default="hakedis")
    # Sales-based models (kat karşılığı / yap-sat / hasılat): contractor share + unit count
    contractor_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    unit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # CR-053: the per-project deal structure (founder's setting). Documents the deal
    # and drives UI labels/hints/defaults; it does NOT compute the P&L (data-driven,
    # §0). Nullable — meaningful for sell-side projects. See DEAL_STRUCTURES.
    deal_structure: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # CR-001-A: free-text type entered when project_type == "other"
    custom_project_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    contract_value_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    contract_value_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    contract_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    eur_try_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("1.0"), server_default="1.0")
    usd_try_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("1.0"), server_default="1.0")

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")

    retention_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"), server_default="10.00")
    contingency_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5.00"), server_default="5.00")

    original_budget_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    approved_variations_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    target_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Manually entered completion percentage (Section 4.1 — editable inline)
    completion_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"), server_default="0")

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    project_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # CR-016-A: residential / kentsel dönüşüm construction area (additive, nullable).
    # Total construction area may exceed the sum of sellable unit areas (common areas).
    construction_gross_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    construction_net_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # CR-015-A: per-project financing overrides. NULL = inherit the company default
    # (see services.financing.effective_financing). Additive; no behavior change off.
    financing_enabled_override: Mapped[bool | None] = mapped_column(nullable=True)
    financing_annual_rate_pct_override: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    company: Mapped["Company"] = relationship(back_populates="projects")  # noqa: F821
    # CR-016-A: the daire dağılımı / unit schedule (empty for non-residential projects).
    # View-only + live-rows-only: the schedule is persisted explicitly by the
    # CR-016-B units service (upsert + soft-delete), not through this collection,
    # so soft-deleted rows never surface in reads/aggregates.
    units: Mapped[list["ProjectUnit"]] = relationship(  # noqa: F821
        "ProjectUnit",
        primaryjoin="and_(Project.id == ProjectUnit.project_id, "
        "ProjectUnit.is_deleted == False)",
        order_by="ProjectUnit.created_at",
        viewonly=True,
    )
