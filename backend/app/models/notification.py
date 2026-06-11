"""notifications table (CR-006-C: in-app bildirim zili).

A lightweight notification feed surfaced via the navbar bell. ``user_id`` NULL
means the notification is visible to every user in the company; otherwise it is
scoped to a single user.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID


class Notification(TimestampSoftDeleteMixin, Base):
    __tablename__ = "notifications"

    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # overdue_payment | margin_warning | budget_overrun | invoice_received | ai_alert
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    related_project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
