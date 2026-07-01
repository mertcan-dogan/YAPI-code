"""automations + automation_runs tables (CR-012 — Otomasyonlar).

A company's enabled+configured instance of a curated automation *template*, plus
an audit/history table of each scheduled or event-driven run. v1 ships two
templates (``template_key``): ``document_auto_file`` (event-driven, on upload) and
``recurring_digest`` (time-driven, fired by the §7 scheduler). The model is kept
template-agnostic (``config`` JSONB) so a later visual builder adds rows, not
schema. RLS / company scoping is enforced in the migration; soft-delete via the
shared mixin (CR-012 never hard-deletes an automation).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB

# v1 template keys (founder's pick). Kept here so the API/service validate against
# one source of truth; a later visual builder extends this set.
TEMPLATE_DOCUMENT_AUTO_FILE = "document_auto_file"
TEMPLATE_RECURRING_DIGEST = "recurring_digest"
TEMPLATE_KEYS = {TEMPLATE_DOCUMENT_AUTO_FILE, TEMPLATE_RECURRING_DIGEST}


class Automation(TimestampSoftDeleteMixin, Base):
    __tablename__ = "automations"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # document_auto_file | recurring_digest
    template_key: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # template-specific config (see CR-012 §4). Portable JSONB (app.models.types).
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Scheduled templates only — drive the §7 due-scan + idempotency guard.
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class AutomationRun(TimestampSoftDeleteMixin, Base):
    """Run history / audit — one row per executed (or skipped) automation run."""

    __tablename__ = "automation_runs"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("automations.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    template_key: Mapped[str] = mapped_column(String(40), nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # success | partial | error | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
