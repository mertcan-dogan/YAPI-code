"""Cost subcategory listing router (CR-018-B).

Merges the global preset taxonomy (constants.COST_SUBCATEGORIES) with a company's
own custom subcategories under a given parent category. Presets come first in
their defined order; customs follow, ordered by usage_count then name. Read-only —
customs are created via POST /custom-categories with a parent_category.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import COST_CATEGORY_KEYS, subcategories_for
from app.db import get_db
from app.deps import CurrentUser
from app.models.custom_category import CustomCostCategory
from app.responses import APIError, success

router = APIRouter(prefix="/cost-subcategories", tags=["cost-subcategories"])


@router.get("")
def list_cost_subcategories(
    user: CurrentUser,
    category: str = Query(..., description="A COST_CATEGORY key"),
    db: Session = Depends(get_db),
):
    if category not in COST_CATEGORY_KEYS:
        raise APIError(400, "INVALID_CATEGORY", "Geçersiz maliyet kategorisi")

    # Presets (global, ordered).
    items = [
        {"key": subkey, "label": label, "custom": False}
        for subkey, label in subcategories_for(category)
    ]

    # Company customs under this parent (company-scoped; forged company_id impossible
    # — we always filter by the authenticated user's company).
    customs = db.execute(
        select(CustomCostCategory)
        .where(
            CustomCostCategory.company_id == user.company_id,
            CustomCostCategory.parent_category == category,
            CustomCostCategory.is_deleted.is_(False),
        )
        .order_by(CustomCostCategory.usage_count.desc(), CustomCostCategory.name.asc())
    ).scalars().all()
    items += [{"key": c.name, "label": c.name, "custom": True} for c in customs]

    return success(items)
