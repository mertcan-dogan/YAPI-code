"""approval_requests table (CR-004-N).

A generic pending-approval record for triggers that don't have a natural
``pending_approval`` flag on their own row: budget changes, subcontractor
contract changes, cost-entry deletions, and variation approvals. The requested
change is captured in ``payload`` and applied to the target row on approval.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin
from app.models.types import GUID as PGUUID
from app.models.types import JSONB


class ApprovalRequest(TimestampSoftDeleteMixin, Base):
    __tablename__ = "approval_requests"

    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)

    # budget_change | subcontractor_change | cost_deletion | variation_approval
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_table: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_try: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[date | datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
