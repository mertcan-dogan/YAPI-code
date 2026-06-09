"""Variation (Ek İş) schemas (CR-003-I)."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.schemas.common import ERR_AMOUNT, ORMModel

VARIATION_STATUSES = ["pending", "approved", "rejected", "disputed"]


class VariationCreate(BaseModel):
    variation_number: str
    title: str
    description: str | None = None
    submitted_date: date
    approved_date: date | None = None
    status: str = "pending"
    value_try: Decimal
    approved_value_try: Decimal | None = None
    cost_impact_try: Decimal = Decimal("0")
    cost_category: str | None = None
    document_url: str | None = None
    notes: str | None = None

    @field_validator("value_try")
    @classmethod
    def _v(cls, v: Decimal) -> Decimal:
        if v is None or v <= 0:
            raise ValueError(ERR_AMOUNT)
        return v

    @field_validator("status")
    @classmethod
    def _s(cls, v: str) -> str:
        if v not in VARIATION_STATUSES:
            raise ValueError("Geçersiz durum")
        return v


class VariationUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    submitted_date: date | None = None
    approved_date: date | None = None
    status: str | None = None
    value_try: Decimal | None = None
    approved_value_try: Decimal | None = None
    cost_impact_try: Decimal | None = None
    cost_category: str | None = None
    document_url: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def _s(cls, v):
        if v is not None and v not in VARIATION_STATUSES:
            raise ValueError("Geçersiz durum")
        return v


class VariationOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    variation_number: str
    title: str
    description: str | None
    submitted_date: date
    approved_date: date | None
    status: str
    value_try: Decimal
    approved_value_try: Decimal | None
    cost_impact_try: Decimal
    margin_impact_try: Decimal
    cost_category: str | None
    document_url: str | None
    notes: str | None
