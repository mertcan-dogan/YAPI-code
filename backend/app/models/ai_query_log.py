"""ai_query_log table — one row per AI Agent (CR-007) request.

Append-only audit trail for the read-only agent. Deliberately separate from
``audit_log`` (§0 B2): that table's ``action`` is ``String(10)`` and its
``record_id`` is NOT nullable, so an agent query — which spans many records and
needs a 14-char ``AI_AGENT_QUERY`` action — cannot be represented there. This
table has no soft-delete: it is purely append-only, like ``audit_log``.

We log only the question, the tool names invoked, and per-tool row counts —
never full record contents (§6.1).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class AIQueryLog(Base):
    __tablename__ = "ai_query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # ["get_vendor_spend", "create_chart", ...]
    tools_used: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {"get_vendor_spend": 42, "compare_vendors": 5}
    row_counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_query_log_company_created", "company_id", "created_at"),
    )
