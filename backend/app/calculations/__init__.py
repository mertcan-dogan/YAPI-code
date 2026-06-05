"""Financial calculation engine (Section 7).

All financial math lives here and is performed in Decimal to avoid floating
point rounding errors (Section 8.1). The frontend never computes — it only
renders values returned by these functions.
"""
from app.calculations.money import D, money, pct, safe_div
from app.calculations.project_financials import compute_project_financials
from app.calculations.cashflow import compute_monthly_cashflow
from app.calculations.rag import compute_rag_status
from app.calculations.equipment import equipment_cost, equipment_duration_days
from app.calculations.subcontractor import (
    subcontractor_revised_contract,
    subcontractor_retention_held,
)

__all__ = [
    "D",
    "money",
    "pct",
    "safe_div",
    "compute_project_financials",
    "compute_monthly_cashflow",
    "compute_rag_status",
    "equipment_cost",
    "equipment_duration_days",
    "subcontractor_revised_contract",
    "subcontractor_retention_held",
]
