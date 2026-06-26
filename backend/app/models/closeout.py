"""project_closeouts table — the Turkish acceptance lifecycle + frozen report.

A closeout row tracks one project through Geçici Kabul → Kesin Hesap → Kesin
Kabul. ``stage`` is the furthest stage reached. At Kesin Hesap the project report
is rendered ONCE and stored verbatim in ``report_data`` (JSONB) with ``frozen_at``
set — the frozen snapshot is never recomputed from live data. Reopening a project
flips ``is_active`` to false (the row is KEPT for the archive/history) and a later
re-close creates a brand-new active row.

This table deliberately does NOT use TimestampSoftDeleteMixin: history is modelled
via ``is_active`` (an archived/superseded row), not soft-delete, so there is no
is_deleted column (mirrors the migration 0043 column set exactly).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class ProjectCloseout(Base):
    __tablename__ = "project_closeouts"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # No index=True here: the composite (company_id, project_id) index
    # (ix_project_closeouts_company_project) is created by migration 0043, matching
    # the repo convention — the model index would duplicate it on create_all DBs.
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )

    # Furthest stage reached: gecici_kabul | kesin_hesap | kesin_kabul.
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gecici_kabul_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    kesin_hesap_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    kesin_kabul_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The FROZEN report snapshot — set ONCE at Kesin Hesap from
    # build_project_report_data(...) and never recomputed for a finalized closeout.
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # False once this closeout was reopened/superseded — kept for the archive.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
