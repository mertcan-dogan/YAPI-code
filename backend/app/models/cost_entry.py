"""cost_entries table (Section 2.3.1)."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Numeric, String, Text
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin


class CostEntry(TimestampSoftDeleteMixin, Base):
    __tablename__ = "cost_entries"
    __table_args__ = (
        CheckConstraint("amount_try > 0", name="ck_cost_entries_amount_positive"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost_category: Mapped[str] = mapped_column(String(50), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subcontractors.id"), nullable=True
    )
    # CR-008-E: optional link to the canonical vendor (additive; supplier_name kept).
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # CR-014-B: USD snapshot — the daily rate applied at this row's relevant date.
    fx_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"), server_default="20.00")
    vat_amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    total_with_vat_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    payment_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", server_default="unpaid")
    date_paid: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_paid_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")

    entry_type: Mapped[str] = mapped_column(String(20), default="actual", server_default="actual")
    # CR-023: commitment relief. On an *actual* entry, points to the committed
    # entry it (partly) fulfils — open_commitment nets these out so a commitment
    # and its later invoice never double-count exposure. Null for standalone
    # actuals and for committed entries themselves. Light optional PO metadata
    # lives on the committed entry.
    commitment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cost_entries.id"), nullable=True
    )
    po_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # CR-003-J: large entries await director approval and are excluded from the dashboard.
    pending_approval: Mapped[bool] = mapped_column(default=False, server_default="false")
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SHA-256 of the captured document bytes — duplicate detection (smart capture).
    document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # CR-024: AI document-extraction confidence (0..1) captured at import time —
    # NULL for manually entered / standard-Excel rows (no AI involved). Display +
    # capture-quality monitoring only; never affects financial math.
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    last_modified_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
