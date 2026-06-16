"""client_invoices table — Hakediş (Section 2.3.1).

invoice_number is UNIQUE per project (Section 8.1 data integrity).
outstanding_try is a generated/computed column: net_due_try - amount_received_try.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Computed, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from app.models.types import GUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampSoftDeleteMixin


class ClientInvoice(TimestampSoftDeleteMixin, Base):
    __tablename__ = "client_invoices"
    __table_args__ = (
        UniqueConstraint("project_id", "invoice_number", name="uq_client_invoices_project_invoice_no"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)

    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    hakkedis_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_type: Mapped[str] = mapped_column(String(30), default="hakedis", server_default="hakedis")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # CR-014-B: USD snapshot (amount + the daily rate applied at the relevant date).
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fx_rate_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"), server_default="20.00")
    vat_amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_with_vat_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    retention_amount_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")
    net_due_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", server_default="unpaid")
    date_received: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount_received_try: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0")

    outstanding_try: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        Computed("net_due_try - amount_received_try", persisted=True),
    )

    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
