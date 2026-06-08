"""Financial calculation engine tests (Section 12.1).

These cover every formula in Section 7 plus the RAG boundary cases called out
explicitly in the Section 15.2 quality checklist.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.calculations import (
    compute_monthly_cashflow,
    compute_project_financials,
    compute_rag_status,
    equipment_cost,
    subcontractor_retention_held,
    subcontractor_revised_contract,
)
from app.calculations.money import money, safe_div


# --------------------------------------------------------------------------
# RAG status — boundary values at 5% and 10% (Section 15.2 checklist)
# --------------------------------------------------------------------------
def _rag(margin, overdue_count=0, max_overdue_days=0, cash=1000, over_cats=0):
    return compute_rag_status(
        {
            "margin_pct": margin,
            "overdue_count": overdue_count,
            "max_overdue_days": max_overdue_days,
            "net_cash_position": cash,
            "categories_over_100pct": over_cats,
        }
    )


def test_rag_red_when_margin_below_5():
    assert _rag(4.99) == "red"
    assert _rag(0) == "red"          # margin exactly 0 -> <5 -> red
    assert _rag(-1) == "red"         # negative margin -> red


def test_rag_amber_at_margin_5_to_10():
    assert _rag(5) == "amber"        # exactly 5 -> not <5, but <10 -> amber
    assert _rag(9.99) == "amber"


def test_rag_green_at_or_above_10():
    assert _rag(10) == "green"       # exactly 10 -> not <10 -> green
    assert _rag(25) == "green"


def test_rag_red_on_negative_cash():
    assert _rag(20, cash=-1) == "red"


def test_rag_red_on_overdue_over_60_days():
    assert _rag(20, max_overdue_days=61) == "red"


def test_rag_amber_on_overdue_present():
    assert _rag(20, overdue_count=1) == "amber"


def test_rag_amber_on_overdue_31_to_60_days():
    assert _rag(20, max_overdue_days=45) == "amber"


def test_rag_red_on_more_than_two_overrun_categories():
    assert _rag(20, over_cats=3) == "red"
    assert _rag(20, over_cats=2) == "green"


# --------------------------------------------------------------------------
# safe_div — no division by zero (Section 8.1)
# --------------------------------------------------------------------------
def test_safe_div_zero_denominator_returns_zero():
    assert safe_div(100, 0) == Decimal("0")
    assert safe_div(0, 0) == Decimal("0")


# --------------------------------------------------------------------------
# Subcontractor (Section 7.1)
# --------------------------------------------------------------------------
def test_subcontractor_revised_contract():
    assert subcontractor_revised_contract(1000, 250) == Decimal("1250.00")


def test_subcontractor_retention_held():
    # 10% of 5000 = 500
    assert subcontractor_retention_held(5000, 10) == Decimal("500.00")
    assert subcontractor_retention_held(0, 10) == Decimal("0.00")


# --------------------------------------------------------------------------
# Equipment cost — day and month rate units (Section 7.1, 12.1)
# --------------------------------------------------------------------------
def test_equipment_cost_day_rate():
    # 10 days at 1000/day + 500 fuel = 10500
    cost = equipment_cost(
        "rented", 1000, "day", date(2025, 1, 1), date(2025, 1, 11), 500
    )
    assert cost == Decimal("10500.00")


def test_equipment_cost_month_rate():
    # 60 days at 30000/month => 2 months => 60000 + 0 fuel
    cost = equipment_cost(
        "rented", 30000, "month", date(2025, 1, 1), date(2025, 3, 2), 0
    )
    assert cost == Decimal("60000.00")


def test_equipment_cost_owned_only_fuel():
    cost = equipment_cost("owned", None, None, date(2025, 1, 1), date(2025, 2, 1), 1500)
    assert cost == Decimal("1500.00")


# --------------------------------------------------------------------------
# Project financials (Section 7.1)
# --------------------------------------------------------------------------
def _project(**over):
    base = {
        "contract_value_try": Decimal("1000000"),
        "original_budget_try": Decimal("800000"),
        "approved_variations_try": Decimal("0"),
        "start_date": date(2025, 1, 1),
        "planned_end_date": date(2025, 12, 31),
        "target_margin_pct": Decimal("15"),
        "completion_pct": Decimal("50"),
    }
    base.update(over)
    return base


def test_revised_budget_with_variations():
    fin = compute_project_financials(
        _project(approved_variations_try=Decimal("50000")), [], [], [], today=date(2025, 6, 1)
    )
    assert fin["revised_budget_try"] == Decimal("850000.00")


def test_margin_calculation_basic():
    # contract 1,000,000; actuals 600,000 ex-vat; no forecast => forecast=actual
    costs = [
        {"amount_try": Decimal("600000"), "total_with_vat_try": Decimal("720000"),
         "amount_paid_try": Decimal("0"), "entry_type": "actual",
         "payment_status": "unpaid", "payment_due_date": None, "date_paid": None,
         "cost_category": "material_concrete"},
    ]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["forecast_final_cost_try"] == Decimal("600000.00")
    assert fin["current_profit_try"] == Decimal("400000.00")
    assert fin["margin_pct"] == Decimal("40.00")


def test_margin_zero_contract_value_no_divide_by_zero():
    # contract value 0 must not raise; margin pct -> 0 (Section 12.1)
    fin = compute_project_financials(
        _project(contract_value_try=Decimal("0"), original_budget_try=Decimal("0")),
        [], [], [], today=date(2025, 6, 1),
    )
    assert fin["margin_pct"] == Decimal("0.00")


def test_forecast_uses_pm_forecast_when_higher():
    # PM forecast for a category higher than actuals -> forecast wins (Section 7.1)
    costs = [
        {"amount_try": Decimal("100000"), "total_with_vat_try": Decimal("120000"),
         "amount_paid_try": Decimal("0"), "entry_type": "actual",
         "payment_status": "unpaid", "payment_due_date": None, "date_paid": None,
         "cost_category": "material_steel"},
    ]
    budgets = [
        {"cost_category": "material_steel", "original_budget_try": Decimal("150000"),
         "approved_variations_try": Decimal("0"), "forecast_final_try": Decimal("200000")},
    ]
    fin = compute_project_financials(_project(), costs, [], budgets, today=date(2025, 6, 1))
    # Forecast-from-budget (200,000) > actual (100,000) -> final cost = 200,000
    assert fin["forecast_final_cost_try"] == Decimal("200000.00")
    # margin = (1,000,000 - 200,000) / 1,000,000 * 100 = 80.00
    assert fin["margin_pct"] == Decimal("80.00")
    steel = next(c for c in fin["categories"] if c["cost_category"] == "material_steel")
    assert steel["variance_try"] == Decimal("50000.00")  # 200k forecast - 150k revised
    assert steel["status"] == "red"  # over budget


def test_revenue_and_cash_position():
    invoices = [
        {"amount_try": Decimal("300000"), "amount_received_try": Decimal("200000"),
         "outstanding_try": Decimal("100000"), "retention_amount_try": Decimal("30000"),
         "net_due_try": Decimal("270000"), "due_date": date(2025, 5, 1),
         "payment_status": "partial", "date_received": date(2025, 5, 10)},
    ]
    costs = [
        {"amount_try": Decimal("150000"), "total_with_vat_try": Decimal("180000"),
         "amount_paid_try": Decimal("150000"), "entry_type": "actual",
         "payment_status": "paid", "payment_due_date": date(2025, 4, 1),
         "date_paid": date(2025, 4, 5), "cost_category": "labour_direct"},
    ]
    fin = compute_project_financials(_project(), costs, invoices, [], today=date(2025, 6, 1))
    assert fin["total_invoiced_try"] == Decimal("300000.00")
    assert fin["total_collected_try"] == Decimal("200000.00")
    assert fin["total_outstanding_try"] == Decimal("100000.00")
    assert fin["total_retention_try"] == Decimal("30000.00")
    # net cash = collected 200,000 - paid_out 150,000 = 50,000
    assert fin["net_cash_position_try"] == Decimal("50000.00")


def test_overdue_detection():
    costs = [
        {"amount_try": Decimal("10000"), "total_with_vat_try": Decimal("12000"),
         "amount_paid_try": Decimal("0"), "entry_type": "actual",
         "payment_status": "unpaid", "payment_due_date": date(2025, 5, 1),
         "date_paid": None, "cost_category": "other"},
    ]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["overdue_count"] == 1
    assert fin["max_overdue_days"] == 31  # May 1 -> Jun 1


def test_currency_eur_does_not_affect_try_totals():
    # EUR amounts present but TRY totals must be unaffected (Section 12.1)
    costs = [
        {"amount_try": Decimal("100000"), "amount_eur": Decimal("3000"),
         "total_with_vat_try": Decimal("120000"), "amount_paid_try": Decimal("0"),
         "entry_type": "actual", "payment_status": "unpaid",
         "payment_due_date": None, "date_paid": None, "cost_category": "material_other"},
    ]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_actual_try"] == Decimal("100000.00")


# --------------------------------------------------------------------------
# Monthly cash flow — cumulative running total, mixed signs (Section 7.2, 12.1)
# --------------------------------------------------------------------------
def test_cumulative_cashflow_mixed_months():
    # CR-002-B: actual outflow = total_with_vat by entry_date (any payment status),
    # actual inflow = amount_received by date_received.
    today = date(2025, 6, 15)
    costs = [
        {"total_with_vat_try": Decimal("50000"), "entry_date": date(2025, 4, 10),
         "payment_status": "unpaid"},
        {"total_with_vat_try": Decimal("30000"), "entry_date": date(2025, 5, 10),
         "payment_status": "unpaid"},
    ]
    invoices = [
        {"amount_received_try": Decimal("100000"), "date_received": date(2025, 5, 20),
         "payment_status": "paid"},
    ]
    rows = compute_monthly_cashflow(costs, invoices, today=today)
    by_month = {r["month"]: r for r in rows}
    # April: -50,000 (cost realised by entry_date even though unpaid)
    assert by_month["2025-04"]["net_try"] == Decimal("-50000.00")
    # May: +100,000 collected - 30,000 cost = +70,000
    assert by_month["2025-05"]["net_try"] == Decimal("70000.00")
    assert by_month["2025-05"]["cumulative_try"] == Decimal("20000.00")


def test_cashflow_future_uses_planned():
    # CR-002-B: future months use planned from due dates of unpaid records.
    today = date(2025, 6, 15)
    costs = [
        {"total_with_vat_try": Decimal("40000"), "entry_date": date(2025, 7, 1),
         "payment_due_date": date(2025, 8, 1), "payment_status": "unpaid"},
    ]
    invoices = [
        {"net_due_try": Decimal("90000"), "amount_received_try": Decimal("0"),
         "due_date": date(2025, 8, 15), "date_received": None, "payment_status": "unpaid"},
    ]
    rows = compute_monthly_cashflow(costs, invoices, today=today)
    by_month = {r["month"]: r for r in rows}
    # August (future): planned 90,000 in - 40,000 out = 50,000
    assert by_month["2025-08"]["net_try"] == Decimal("50000.00")
