"""ai_feedback table — CR-024-A. One row per user 👍/👎 on an agent answer.

Append-only (no soft-delete), company-scoped + RLS, mirroring ai_query_log
(CR-007). The ``question`` is denormalized so feedback stays readable even if the
linked ai_query_log row is later pruned. ``ai_query_log_id`` is nullable so a
degraded answer (no log row) can still be rated.

Privacy (CR-024 §0.2.5): free-text ``comment`` is stored here under per-company
RLS and is NEVER forwarded to error monitoring / 3rd parties.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import GUID as PGUID


class AIFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Nullable link to the answered query (a degraded answer has no log row).
    ai_query_log_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUID(as_uuid=True), ForeignKey("ai_query_log.id"), nullable=True
    )
    # Denormalized copy so feedback is readable even if the log row is pruned.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)  # "up" | "down"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ai_feedback_company_created", "company_id", "created_at"),
    )
