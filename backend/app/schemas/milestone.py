"""Milestone schemas (CR-019-A) — SCHEDULE lane only (no monetary fields)."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

from app.constants import MILESTONE_STATUSES
from app.schemas.common import ORMModel

ERR_TITLE = "Kilometre taşı başlığı zorunludur"
ERR_WEIGHT = "Ağırlık 0'dan büyük olmalıdır"
ERR_STATUS = "Geçersiz kilometre taşı durumu"


def _clean_title(v: str) -> str:
    if v is None or not str(v).strip():
        raise ValueError(ERR_TITLE)
    return str(v).strip()


class MilestoneCreate(BaseModel):
    title: str
    stage: str | None = None
    planned_date: date | None = None
    weight: Decimal = Decimal("1")
    status: str = "pending"
    completed_date: date | None = None
    sort_order: int = 0
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _clean_title(v)

    @field_validator("weight")
    @classmethod
    def _weight(cls, v: Decimal) -> Decimal:
        # Unset/zero weights default to 1 in the rollup; reject negatives outright.
        if v is None:
            return Decimal("1")
        if v < 0:
            raise ValueError(ERR_WEIGHT)
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in MILESTONE_STATUSES:
            raise ValueError(ERR_STATUS)
        return v


class MilestoneUpdate(BaseModel):
    title: str | None = None
    stage: str | None = None
    planned_date: date | None = None
    weight: Decimal | None = None
    status: str | None = None
    completed_date: date | None = None
    sort_order: int | None = None
    notes: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return None if v is None else _clean_title(v)

    @field_validator("weight")
    @classmethod
    def _weight(cls, v):
        if v is not None and v < 0:
            raise ValueError(ERR_WEIGHT)
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in MILESTONE_STATUSES:
            raise ValueError(ERR_STATUS)
        return v


class MilestoneReorderItem(BaseModel):
    id: uuid.UUID
    sort_order: int


class MilestoneReorder(BaseModel):
    items: list[MilestoneReorderItem]


class MilestoneOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    stage: str | None
    planned_date: date | None
    weight: Decimal
    status: str
    completed_date: date | None
    sort_order: int
    notes: str | None
