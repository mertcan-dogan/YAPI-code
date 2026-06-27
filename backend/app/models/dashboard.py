"""dashboards table — saved Report Studio panos/canvases (CR-034).

A Dashboard is pure metadata: a saved canvas of ``widgets`` (a JSONB array of
KPI/chart/table/text/report widgets, each carrying its react-grid-layout cell
coords and either an inline CR-032 spec, a referenced ``report_id``, or free
text) plus dashboard-global ``date_range``/``comparison``/``filters`` and
presentation/ownership fields. It stores no computed results — each widget spec
is re-executed by the engine on demand. ``owner_id`` gates edit/delete;
``visibility`` ('private' by default) controls who in the company may view it.
RLS / company scoping is enforced in migration 0045; soft-delete via the shared
mixin (the mixin already provides id/created_at/updated_at/is_deleted/deleted_at).
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class Dashboard(TimestampSoftDeleteMixin, Base):
    __tablename__ = "dashboards"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Ownership/edit gate — the user who may modify or delete this dashboard.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # The widget array (KPI/chart/table/text/report). Portable JSONB; defaults [].
    # NOTE: server_default is the dialect-portable ``'[]'`` (not ``'[]'::jsonb``) so
    # the SQLite test create_all parses it; Postgres casts the literal to jsonb. The
    # prod table's default comes from migration 0045, which uses ``'[]'::jsonb``.
    widgets: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    # Dashboard-global query context, merged into each data widget's spec unless
    # the widget overrides it. All optional.
    date_range: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    comparison: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    filters: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # private | company (team reserved) — defaults to private.
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    # Optional free-form labels/tags for organising dashboards.
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
