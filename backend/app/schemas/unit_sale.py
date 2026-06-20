"""Unit-sale (daire satış) schemas (CR-031-A)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.constants import OWNER_SIDES
from app.schemas.common import ERR_AMOUNT, ORMModel


class UnitSaleCreate(BaseModel):
    project_unit_id: uuid.UUID | None = None
    unit_label: str
    unit_type: str | None = None
    floor: str | None = None
    gross_m2: Decimal | None = None
    net_m2: Decimal | None = None
    buyer_name: str | None = None
    sale_price_try: Decimal
    sale_date: date
    payment_type: str | None = None
    installment_note: str | None = None
    deed_status: str | None = None
    deed_date: date | None = None
    owner_side: str = "yuklenici"
    notes: str | None = None

    @field_validator("sale_price_try")
    @classmethod
    def _price(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v

    @field_validator("owner_side")
    @classmethod
    def _side(cls, v: str) -> str:
        if v not in OWNER_SIDES:
            raise ValueError("Geçersiz mülkiyet tarafı")
        return v


class UnitSaleUpdate(BaseModel):
    project_unit_id: uuid.UUID | None = None
    unit_label: str | None = None
    unit_type: str | None = None
    floor: str | None = None
    gross_m2: Decimal | None = None
    net_m2: Decimal | None = None
    buyer_name: str | None = None
    sale_price_try: Decimal | None = None
    sale_date: date | None = None
    payment_type: str | None = None
    installment_note: str | None = None
    deed_status: str | None = None
    deed_date: date | None = None
    owner_side: str | None = None
    notes: str | None = None

    @field_validator("sale_price_try")
    @classmethod
    def _price(cls, v):
        if v is not None and v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v

    @field_validator("owner_side")
    @classmethod
    def _side(cls, v):
        if v is not None and v not in OWNER_SIDES:
            raise ValueError("Geçersiz mülkiyet tarafı")
        return v


class UnitSaleOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_unit_id: uuid.UUID | None
    unit_label: str
    unit_type: str | None
    floor: str | None
    gross_m2: Decimal | None
    net_m2: Decimal | None
    buyer_name: str | None
    sale_price_try: Decimal
    sale_date: date
    fx_rate_usd: Decimal | None
    sale_price_usd: Decimal | None
    payment_type: str | None
    installment_note: str | None
    deed_status: str | None
    deed_date: date | None
    owner_side: str
    notes: str | None
    created_at: datetime
