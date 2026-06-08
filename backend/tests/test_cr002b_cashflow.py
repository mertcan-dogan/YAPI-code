"""CR-002-B: cash flow actual calculation from entry_date / date_received."""
from datetime import date
from decimal import Decimal

from app.calculations import compute_monthly_cashflow


def test_actual_outflow_by_entry_date_regardless_of_payment():
    today = date(2025, 6, 15)
    # 5 January cost entries, all unpaid — must still count in January actual out.
    costs = [
        {"total_with_vat_try": Decimal("10000"), "entry_date": date(2025, 1, 5), "payment_status": "unpaid"}
        for _ in range(5)
    ]
    rows = {r["month"]: r for r in compute_monthly_cashflow(costs, [], today=today)}
    assert rows["2025-01"]["actual_out_try"] == Decimal("50000.00")


def test_actual_inflow_by_date_received():
    today = date(2025, 6, 15)
    invoices = [
        {"amount_received_try": Decimal("120000"), "date_received": date(2025, 2, 10), "payment_status": "partial"},
        {"amount_received_try": Decimal("80000"), "date_received": date(2025, 2, 20), "payment_status": "paid"},
        # not yet received -> excluded from actual inflow
        {"amount_received_try": Decimal("0"), "date_received": None, "due_date": date(2025, 2, 1), "payment_status": "unpaid"},
    ]
    rows = {r["month"]: r for r in compute_monthly_cashflow([], invoices, today=today)}
    assert rows["2025-02"]["actual_in_try"] == Decimal("200000.00")


def test_cumulative_running_total():
    today = date(2025, 6, 15)
    costs = [
        {"total_with_vat_try": Decimal("40000"), "entry_date": date(2025, 3, 1), "payment_status": "unpaid"},
        {"total_with_vat_try": Decimal("20000"), "entry_date": date(2025, 4, 1), "payment_status": "unpaid"},
    ]
    invoices = [
        {"amount_received_try": Decimal("100000"), "date_received": date(2025, 4, 15), "payment_status": "paid"},
    ]
    rows = {r["month"]: r for r in compute_monthly_cashflow(costs, invoices, today=today)}
    # Mar: -40,000 ; Apr: 100,000 - 20,000 = +80,000 ; cumulative Apr = +40,000
    assert rows["2025-03"]["cumulative_try"] == Decimal("-40000.00")
    assert rows["2025-04"]["cumulative_try"] == Decimal("40000.00")
