"""Budget templates router (CR-003-L). Built-in presets + company custom."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import COST_CATEGORY_KEYS
from app.db import get_db
from app.deps import CurrentUser, DirectorUser
from app.models.budget_template import CustomBudgetTemplate
from app.responses import APIError, success

router = APIRouter(prefix="/budget-templates", tags=["budget-templates"])

# Built-in presets (CR-003-L 13.2) — percentages map to the 15 standard categories.
PRESETS = [
    {"id": "preset:altyapi", "name": "Altyapı — Yol/Demiryolu", "is_preset": True, "distribution": {
        "labour_direct": 25, "material_aggregate": 20, "material_other": 18,
        "equipment_rented": 20, "subcontractor": 10, "site_overhead": 7}},
    {"id": "preset:denizel", "name": "Denizel / Kıyı", "is_preset": True, "distribution": {
        "labour_direct": 20, "equipment_rented": 25, "material_steel": 20,
        "subcontractor": 20, "site_overhead": 15}},
    {"id": "preset:atiksu", "name": "Atıksu Arıtma", "is_preset": True, "distribution": {
        "labour_direct": 15, "material_pipes": 20, "material_concrete": 18, "equipment_rented": 12,
        "subcontractor": 22, "engineering_design": 8, "site_overhead": 5}},
    {"id": "preset:bina", "name": "Bina İnşaatı", "is_preset": True, "distribution": {
        "labour_direct": 20, "material_concrete": 22, "material_steel": 18,
        "equipment_rented": 10, "subcontractor": 20, "site_overhead": 10}},
]


class TemplateCreate(BaseModel):
    name: str
    distribution: dict[str, float]

    @field_validator("distribution")
    @classmethod
    def _dist(cls, v: dict) -> dict:
        for cat in v:
            if cat not in COST_CATEGORY_KEYS:
                raise ValueError(f"Geçersiz kategori: {cat}")
        return v


@router.get("")
def list_templates(user: CurrentUser, db: Session = Depends(get_db)):
    custom = db.execute(
        select(CustomBudgetTemplate).where(
            CustomBudgetTemplate.company_id == user.company_id,
            CustomBudgetTemplate.is_deleted.is_(False),
        )
    ).scalars().all()
    custom_out = [
        {"id": str(c.id), "name": c.name, "is_preset": False, "distribution": c.distribution}
        for c in custom
    ]
    return success(PRESETS + custom_out)


@router.post("")
def create_template(payload: TemplateCreate, user: DirectorUser, db: Session = Depends(get_db)):
    t = CustomBudgetTemplate(company_id=user.company_id, name=payload.name, distribution=payload.distribution)
    db.add(t)
    db.commit()
    db.refresh(t)
    return success({"id": str(t.id), "name": t.name, "is_preset": False, "distribution": t.distribution})


@router.delete("/{template_id}")
def delete_template(template_id: str, user: DirectorUser, db: Session = Depends(get_db)):
    # Presets are built-in and not deletable.
    if template_id.startswith("preset:"):
        raise APIError(422, "VALIDATION_ERROR", "Hazır şablonlar silinemez")
    try:
        tid = uuid.UUID(template_id)
    except (ValueError, AttributeError):
        raise APIError(404, "NOT_FOUND", "Şablon bulunamadı")
    t = db.execute(
        select(CustomBudgetTemplate).where(
            CustomBudgetTemplate.id == tid,
            CustomBudgetTemplate.company_id == user.company_id,
            CustomBudgetTemplate.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if t is None:
        raise APIError(404, "NOT_FOUND", "Şablon bulunamadı")
    t.is_deleted = True
    db.commit()
    return success({"id": str(t.id), "deleted": True})
