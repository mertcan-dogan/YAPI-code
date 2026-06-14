"""ai_conversations table — per-user AI Asistan chat history (cross-device sync).

Each row is one conversation owned by a single user. ``messages`` holds the full
turn list as JSON ([{role, text, at?}, ...]). Conversations are private to the
user; ``company_id`` is kept for company-scoped isolation parity with the rest of
the schema.
"""
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class AIConversation(TimestampSoftDeleteMixin, Base):
    __tablename__ = "ai_conversations"

    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # [{role: "user"|"ai", text: str, at?: iso8601}]
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
