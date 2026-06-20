"""Landowner-payment (arsa sahibi ödemesi) schemas (CR-031-B)."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.schemas.common import ERR_AMOUNT, ORMModel


class LandownerPaymentCreate(BaseModel):
    payer_name: str | None = None
    committed_total_try: Decimal | None = None
    payment_date: date
    amount_try: Decimal
    payment_type: str | None = None
    description: str | None = None
    notes: str | None = None

    @field_validator("amount_try")
    @classmethod
    def _amt(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v


class LandownerPaymentUpdate(BaseModel):
    payer_name: str | None = None
    committed_total_try: Decimal | None = None
    payment_date: date | None = None
    amount_try: Decimal | None = None
    payment_type: str | None = None
    description: str | None = None
    notes: str | None = None

    @field_validator("amount_try")
    @classmethod
    def _amt(cls, v):
        if v is not None and v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v


class LandownerPaymentOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    payer_name: str | None
    committed_total_try: Decimal | None
    payment_date: date
    amount_try: Decimal
    fx_rate_usd: Decimal | None
    amount_usd: Decimal | None
    payment_type: str | None
    description: str | None
    notes: str | None
    created_at: datetime
