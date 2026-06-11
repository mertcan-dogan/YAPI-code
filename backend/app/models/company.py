"""companies table (Section 2.3.1)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID  # noqa: F401 (kept for symmetry)


class Company(TimestampSoftDeleteMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    tax_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_currency: Mapped[str] = mapped_column(String(3), default="TRY", server_default="TRY")
    retention_default_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00"), server_default="10.00"
    )
    vat_rate_default: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("20.00"), server_default="20.00"
    )
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscription_status: Mapped[str] = mapped_column(
        String(20), default="trial", server_default="trial"
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fiscal_year_start_month: Mapped[int] = mapped_column(default=1, server_default="1")
    # CR-003-J approval workflow settings
    approvals_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    cost_approval_threshold_try: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("500000"), server_default="500000"
    )
    # CR-004-N: each trigger has its own toggle (default On per spec).
    require_budget_approval: Mapped[bool] = mapped_column(default=True, server_default="true")
    require_subcontractor_approval: Mapped[bool] = mapped_column(default=True, server_default="true")
    require_deletion_approval: Mapped[bool] = mapped_column(default=True, server_default="true")
    require_variation_approval: Mapped[bool] = mapped_column(default=True, server_default="true")

    users: Mapped[list["User"]] = relationship(back_populates="company")  # noqa: F821
    projects: Mapped[list["Project"]] = relationship(back_populates="company")  # noqa: F821
