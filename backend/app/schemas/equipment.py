"""Equipment log schemas (Section 4.8)."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.constants import OWNERSHIP_TYPES, RATE_UNITS
from app.schemas.common import ORMModel


class EquipmentCreate(BaseModel):
    equipment_name: str
    ownership_type: str
    supplier_name: str | None = None
    rate_try: Decimal | None = None
    rate_unit: str | None = None
    deployment_start: date
    deployment_end: date | None = None
    fuel_maintenance_try: Decimal = Decimal("0")
    notes: str | None = None

    @field_validator("ownership_type")
    @classmethod
    def _own(cls, v: str) -> str:
        if v not in OWNERSHIP_TYPES:
            raise ValueError("Geçersiz sahiplik türü")
        return v

    @field_validator("rate_unit")
    @classmethod
    def _unit(cls, v):
        if v is not None and v not in RATE_UNITS:
            raise ValueError("Geçersiz birim")
        return v


class EquipmentUpdate(BaseModel):
    equipment_name: str | None = None
    ownership_type: str | None = None
    supplier_name: str | None = None
    rate_try: Decimal | None = None
    rate_unit: str | None = None
    deployment_start: date | None = None
    deployment_end: date | None = None
    fuel_maintenance_try: Decimal | None = None
    notes: str | None = None


class EquipmentOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    equipment_name: str
    ownership_type: str
    supplier_name: str | None
    rate_try: Decimal | None
    rate_unit: str | None
    deployment_start: date
    deployment_end: date | None
    fuel_maintenance_try: Decimal
    notes: str | None
    # computed
    duration_days: int | None = None
    total_cost_try: Decimal | None = None
