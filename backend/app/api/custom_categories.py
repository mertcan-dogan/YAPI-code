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
    """Create a custom category/subcategory, or bump usage_count if it already exists.

    Dedup is by (company_id, parent_category, name_normalized). CR-018-B note: the
    DB unique constraint can't enforce this when parent_category IS NULL (SQL NULLs
    are distinct), so the top-level dedup that CR-001-D relied on is re-established
    here in app code — the parent filter below uses ``.is_(None)`` for NULL parents.
    """
    norm = normalize(payload.name)
    parent = payload.parent_category  # already validated to be a COST_CATEGORY key or None
    parent_filter = (
        CustomCostCategory.parent_category.is_(None)
        if parent is None
        else CustomCostCategory.parent_category == parent
    )
    existing = db.execute(
        select(CustomCostCategory).where(
            CustomCostCategory.company_id == user.company_id,
            parent_filter,
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
        company_id=user.company_id, parent_category=parent,
        name=payload.name.strip(), name_normalized=norm, usage_count=1,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return success(CustomCategoryOut.model_validate(cat).model_dump(mode="json"))
