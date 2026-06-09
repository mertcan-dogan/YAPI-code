"""CR-003-A: budget RAG-dot status + variance semantics."""
from datetime import date
from decimal import Decimal

from app.calculations.project_financials import _compute_category_rows


def _row(cat="material_steel", original="0", forecast=None, invoiced=None):
    budgets = [{"cost_category": cat, "original_budget_try": Decimal(original),
                "approved_variations_try": Decimal("0"),
                "forecast_final_try": Decimal(forecast) if forecast is not None else None}]
    costs = []
    if invoiced is not None:
        costs.append({"cost_category": cat, "amount_try": Decimal(invoiced), "entry_type": "actual",
                      "amount_paid_try": Decimal("0")})
    rows = _compute_category_rows(costs, budgets, date(2026, 6, 1))
    return next(r for r in rows if r["cost_category"] == cat)


def test_no_budget_is_gray():
    assert _row(original="0")["status"] == "gray"


def test_under_budget_is_green():
    # budget 100k, spent 50k (<85%), forecast = budget -> variance 0
    r = _row(original="100000", forecast="100000", invoiced="50000")
    assert r["status"] == "green"
    assert Decimal(str(r["variance_try"])) == Decimal("0.00")


def test_near_budget_is_amber():
    # spent 90k of 100k = 90% (85-100), forecast = budget
    r = _row(original="100000", forecast="100000", invoiced="90000")
    assert r["status"] == "amber"


def test_over_budget_is_red_positive_variance():
    # forecast 130k > budget 100k -> variance positive -> red
    r = _row(original="100000", forecast="130000", invoiced="50000")
    assert r["status"] == "red"
    assert Decimal(str(r["variance_try"])) > 0


def test_overspent_pct_over_100_is_red():
    # invoiced 120k of 100k budget -> %spent > 100 -> red
    r = _row(original="100000", forecast="100000", invoiced="120000")
    assert r["status"] == "red"
