"""Custom cost categories router (CR-001-D)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.custom_category import CustomCostCategory
from app.responses import success
from app.schemas.custom_category import CustomCategoryCreate, CustomCategoryOut

router = APIRouter(prefix="/custom-categories", tags=["custom-categories"])


def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


@router.get("")
def list_custom_categories(user: CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(
        select(CustomCostCategory)
        .where(
            CustomCostCategory.company_id == user.company_id,
            CustomCostCategory.is_deleted.is_(False),
        )
        .order_by(CustomCostCategory.usage_count.desc(), CustomCostCategory.name.asc())
    ).scalars().all()
    return success([CustomCategoryOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("")
def create_custom_category(payload: CustomCategoryCreate, user: CurrentUser, db: Session = Depends(get_db)):
    """Create a custom category, or bump usage_count if it already exists."""
    norm = normalize(payload.name)
    existing = db.execute(
        select(CustomCostCategory).where(
            CustomCostCategory.company_id == user.company_id,
            CustomCostCategory.name_normalized == norm,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_deleted = False
        existing.usage_count = (existing.usage_count or 0) + 1
        db.commit()
        db.refresh(existing)
        return success(CustomCategoryOut.model_validate(existing).model_dump(mode="json"))

    cat = CustomCostCategory(
        company_id=user.company_id, name=payload.name.strip(), name_normalized=norm, usage_count=1
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return success(CustomCategoryOut.model_validate(cat).model_dump(mode="json"))
