"""reports table — saved Report Studio specs (CR-033).

A Report is pure metadata: a saved CR-032 report *spec* (the semantic-layer query
definition) plus presentation/ownership fields. It stores no computed results —
the spec is re-executed by the engine on demand. ``owner_id`` gates edit/delete;
``visibility`` ('private' by default) controls who in the company may view it.
RLS / company scoping is enforced in migration 0044; soft-delete via the shared
mixin (the mixin already provides id/created_at/updated_at/is_deleted/deleted_at).
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class Report(TimestampSoftDeleteMixin, Base):
    __tablename__ = "reports"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Ownership/edit gate — the user who may modify or delete this report.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # The saved CR-032 spec (semantic-layer query definition). Portable JSONB.
    spec: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # private | (future: company/shared) — defaults to private.
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    # Optional free-form labels/tags for organising reports.
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
