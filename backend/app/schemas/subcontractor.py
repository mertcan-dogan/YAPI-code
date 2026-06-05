"""Subcontractor schemas (Section 4.5)."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.constants import SUBCONTRACTOR_STATUSES
from app.schemas.common import ERR_CONTRACT, ERR_RETENTION, ORMModel


class SubcontractorCreate(BaseModel):
    name: str
    scope_of_work: str | None = None
    contract_value_try: Decimal
    approved_variations_try: Decimal = Decimal("0")
    retention_pct: Decimal = Decimal("10.00")
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    notes: str | None = None

    @field_validator("contract_value_try")
    @classmethod
    def _cv(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_CONTRACT)
        return v

    @field_validator("retention_pct")
    @classmethod
    def _ret(cls, v: Decimal) -> Decimal:
        if v is None or v < 0 or v > 50:
            raise ValueError(ERR_RETENTION)
        return v


class SubcontractorUpdate(BaseModel):
    name: str | None = None
    scope_of_work: str | None = None
    contract_value_try: Decimal | None = None
    approved_variations_try: Decimal | None = None
    retention_pct: Decimal | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    status: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in SUBCONTRACTOR_STATUSES:
            raise ValueError("Geçersiz alt yüklenici durumu")
        return v


class SubcontractorOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    scope_of_work: str | None
    contract_value_try: Decimal
    approved_variations_try: Decimal
    retention_pct: Decimal
    contract_start_date: date | None
    contract_end_date: date | None
    status: str
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    notes: str | None
