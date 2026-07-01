"""Project closeout schemas — stage transitions + read models."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CloseoutStageIn(BaseModel):
    """Body for a stage-advance action: the acceptance date for that stage."""

    date: date


class CloseoutOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    company_id: uuid.UUID
    stage: str | None
    gecici_kabul_date: date | None
    kesin_hesap_date: date | None
    kesin_kabul_date: date | None
    is_active: bool
    frozen_at: datetime | None
    reopened_at: datetime | None
    created_at: datetime
