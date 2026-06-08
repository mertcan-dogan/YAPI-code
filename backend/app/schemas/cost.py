"""Cost entry schemas (Section 4.3, 9.3)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator

from app.constants import COST_CATEGORY_KEYS, COST_PAYMENT_STATUSES, ENTRY_TYPES
from app.schemas.common import (
    ERR_AMOUNT,
    ERR_DUE_BEFORE_ENTRY,
    ORMModel,
    valid_entry_date,
)


class CostEntryCreate(BaseModel):
    entry_date: date
    entry_type: str = "actual"
    cost_category: str
    subcategory: str | None = None
    supplier_name: str | None = None
    subcontractor_id: uuid.UUID | None = None
    description: str | None = None
    invoice_number: str | None = None
    amount_try: Decimal
    amount_eur: Decimal | None = None
    amount_usd: Decimal | None = None
    vat_rate: Decimal = Decimal("20.00")
    payment_due_date: date | None = None
    payment_status: str = "unpaid"
    date_paid: date | None = None
    amount_paid_try: Decimal = Decimal("0")
    document_url: str | None = None
    notes: str | None = None

    @field_validator("amount_try")
    @classmethod
    def _amt(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v

    @field_validator("cost_category")
    @classmethod
    def _cat(cls, v: str) -> str:
        # Standard enum key OR a company custom category (CR-001-D). Custom
        # categories are free text (validated for length only).
        if v in COST_CATEGORY_KEYS:
            return v
        v = (v or "").strip()
        if not v:
            raise ValueError("Geçersiz maliyet kategorisi")
        if len(v) > 50:
            raise ValueError("Kategori en fazla 50 karakter olabilir")
        return v

    @field_validator("entry_type")
    @classmethod
    def _etype(cls, v: str) -> str:
        if v not in ENTRY_TYPES:
            raise ValueError("Geçersiz giriş tipi")
        return v

    @field_validator("payment_status")
    @classmethod
    def _pstatus(cls, v: str) -> str:
        if v not in COST_PAYMENT_STATUSES:
            raise ValueError("Geçersiz ödeme durumu")
        return v

    @field_validator("entry_date")
    @classmethod
    def _edate(cls, v: date) -> date:
        return valid_entry_date(v)

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        if v is not None and len(v) > 1000:
            raise ValueError("Notlar en fazla 1000 karakter olabilir")
        return v

    # CR-002-I: strip any HTML from free-text fields (XSS protection).
    @field_validator("description", "supplier_name", "subcategory", "notes", "invoice_number")
    @classmethod
    def _sanitize(cls, v):
        from app.utils.sanitize import sanitize_text

        return sanitize_text(v)

    @model_validator(mode="after")
    def _due(self):
        if self.payment_due_date and self.payment_due_date < self.entry_date:
            raise ValueError(ERR_DUE_BEFORE_ENTRY)
        return self


class CostEntryUpdate(BaseModel):
    entry_date: date | None = None
    entry_type: str | None = None
    cost_category: str | None = None
    subcategory: str | None = None
    supplier_name: str | None = None
    subcontractor_id: uuid.UUID | None = None
    description: str | None = None
    invoice_number: str | None = None
    amount_try: Decimal | None = None
    amount_eur: Decimal | None = None
    vat_rate: Decimal | None = None
    payment_due_date: date | None = None
    payment_status: str | None = None
    date_paid: date | None = None
    amount_paid_try: Decimal | None = None
    document_url: str | None = None
    notes: str | None = None

    @field_validator("amount_try")
    @classmethod
    def _amt(cls, v):
        if v is not None and v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v


class CostEntryOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    entry_date: date
    entry_type: str
    cost_category: str
    subcategory: str | None
    supplier_name: str | None
    subcontractor_id: uuid.UUID | None
    description: str | None
    invoice_number: str | None
    amount_try: Decimal
    amount_eur: Decimal | None
    amount_usd: Decimal | None
    vat_rate: Decimal
    vat_amount_try: Decimal
    total_with_vat_try: Decimal
    payment_due_date: date | None
    payment_status: str
    date_paid: date | None
    amount_paid_try: Decimal
    document_url: str | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
