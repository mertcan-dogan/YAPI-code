"""ai_alerts table (Section 2.3.1)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIAlert(Base):
    __tablename__ = "ai_alerts"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )  # null = company-level alert
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title_tr: Mapped[str] = mapped_column(Text, nullable=False)
    body_tr: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_actioned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # CR-003-M: user feedback — useful / wrong / irrelevant
    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dismissed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # CR-022-A: record linkage + per-issue dedup for assurance/anomaly findings.
    # NULL on all pre-existing (health) alerts → they stay unaffected; the
    # Finans Güvence view treats "dedup_key IS NOT NULL" as an assurance finding.
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # cost_entry|client_invoice|project
    source_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_ai_alerts_company_dedup", "company_id", "dedup_key"),
    )
