"""Custom cost category schemas (CR-001-D)."""
import uuid

from pydantic import BaseModel, field_validator

from app.schemas.common import ORMModel


class CustomCategoryCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Kategori adı zorunludur")
        if len(v) > 255:
            raise ValueError("Kategori adı en fazla 255 karakter olabilir")
        return v


class CustomCategoryOut(ORMModel):
    id: uuid.UUID
    name: str
    usage_count: int
