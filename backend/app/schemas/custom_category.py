"""Custom cost category schemas (CR-001-D; parent_category added CR-018-B)."""
import uuid

from pydantic import BaseModel, field_validator

from app.constants import COST_CATEGORY_KEYS
from app.schemas.common import ORMModel


class CustomCategoryCreate(BaseModel):
    name: str
    # CR-018-B: NULL = a top-level custom category (CR-001-D); a COST_CATEGORY key
    # = a custom subcategory under that standard category.
    parent_category: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Kategori adı zorunludur")
        if len(v) > 255:
            raise ValueError("Kategori adı en fazla 255 karakter olabilir")
        return v

    @field_validator("parent_category")
    @classmethod
    def _parent(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v not in COST_CATEGORY_KEYS:
            raise ValueError("Geçersiz üst kategori")
        return v


class CustomCategoryOut(ORMModel):
    id: uuid.UUID
    name: str
    parent_category: str | None = None
    usage_count: int
