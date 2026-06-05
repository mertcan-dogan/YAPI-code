"""Budget line item schemas (Section 4.3)."""
import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import ORMModel


class BudgetForecastUpdate(BaseModel):
    """PUT /projects/{id}/budget/{category} — update the PM forecast."""
    forecast_final_try: Decimal | None = None
    original_budget_try: Decimal | None = None
    approved_variations_try: Decimal | None = None


class BudgetLineOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    cost_category: str
    original_budget_try: Decimal
    approved_variations_try: Decimal
    forecast_final_try: Decimal | None
