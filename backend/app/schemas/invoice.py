"""Client invoice (Hakediş) schemas (Section 4.4, 9.3)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator

from app.constants import INVOICE_PAYMENT_STATUSES, INVOICE_TYPES
from app.schemas.common import ERR_AMOUNT, ERR_DUE_BEFORE_ENTRY, ORMModel


class ClientInvoiceCreate(BaseModel):
    invoice_number: str
    invoice_date: date
    hakkedis_period: str | None = None
    invoice_type: str = "hakedis"
    description: str | None = None
    amount_try: Decimal
    amount_eur: Decimal | None = None
    vat_rate: Decimal = Decimal("20.00")
    retention_amount_try: Decimal = Decimal("0")
    due_date: date
    document_url: str | None = None

    @field_validator("amount_try")
    @classmethod
    def _amt(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v

    @field_validator("invoice_type")
    @classmethod
    def _itype(cls, v: str) -> str:
        if v not in INVOICE_TYPES:
            raise ValueError("Geçersiz fatura türü")
        return v

    @model_validator(mode="after")
    def _due(self):
        if self.due_date < self.invoice_date:
            raise ValueError(ERR_DUE_BEFORE_ENTRY)
        return self


class ClientInvoiceUpdate(BaseModel):
    invoice_date: date | None = None
    hakkedis_period: str | None = None
    invoice_type: str | None = None
    description: str | None = None
    amount_try: Decimal | None = None
    amount_eur: Decimal | None = None
    vat_rate: Decimal | None = None
    retention_amount_try: Decimal | None = None
    due_date: date | None = None
    payment_status: str | None = None
    date_received: date | None = None
    amount_received_try: Decimal | None = None
    document_url: str | None = None
    notes: str | None = None

    @field_validator("payment_status")
    @classmethod
    def _ps(cls, v):
        if v is not None and v not in INVOICE_PAYMENT_STATUSES:
            raise ValueError("Geçersiz ödeme durumu")
        return v


class ClientInvoiceOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    invoice_number: str
    invoice_date: date
    hakkedis_period: str | None
    invoice_type: str
    description: str | None
    amount_try: Decimal
    amount_eur: Decimal | None
    amount_usd: Decimal | None = None
    fx_rate_usd: Decimal | None = None
    vat_rate: Decimal
    vat_amount_try: Decimal
    total_with_vat_try: Decimal
    retention_amount_try: Decimal
    net_due_try: Decimal
    due_date: date
    payment_status: str
    date_received: date | None
    amount_received_try: Decimal
    outstanding_try: Decimal
    document_url: str | None
    notes: str | None
    # CR-024: AI document-extraction confidence (0..1); NULL for manual rows.
    # Display / monitoring only — never feeds the financial math.
    extraction_confidence: float | None = None
    created_at: datetime
