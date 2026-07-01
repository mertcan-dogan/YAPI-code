"""workspace_items table — per-user "Çalışma Alanım" pinned snapshots (CR-008-A).

Mirrors the ai_conversations pattern: per-user, company-scoped, soft-deleted,
client-generated id. Each item is a SNAPSHOT (frozen at pin time, §0.2): for a
``chart`` the full AgentChartSpec; for an ``analysis`` ``{answer_markdown, citations}``.
``layout`` ({x, y, w, h} grid cell) is persisted by the reorder endpoint (CR-008-B).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class WorkspaceItem(TimestampSoftDeleteMixin, Base):
    __tablename__ = "workspace_items"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # "chart" | "analysis"
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # chart -> AgentChartSpec; analysis -> {answer_markdown, citations}
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Provenance only (not an FK — conversations are per-user and may be deleted).
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    # Grid cell {x, y, w, h}; null until the board is arranged (CR-008-B).
    layout: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
