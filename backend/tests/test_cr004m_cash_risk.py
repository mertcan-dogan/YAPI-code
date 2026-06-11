"""CR-004-M: 30/60/90-day cash-need windows."""
from datetime import date, timedelta
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services.financials import cash_need_windows

TODAY = date(2026, 6, 10)


def _cost(a, due_offset, total, **kw):
    kw.setdefault("payment_status", "unpaid")
    return CostEntry(
        project_id=a["project"].id, company_id=a["company"].id, created_by=a["users"][ROLE_DIRECTOR].id,
        entry_date=TODAY, cost_category="materials", amount_try=Decimal(total),
        total_with_vat_try=Decimal(total),
        payment_due_date=TODAY + timedelta(days=due_offset), **kw,
    )


def _inv(a, due_offset, amount, **kw):
    return ClientInvoice(
        project_id=a["project"].id, company_id=a["company"].id, created_by=a["users"][ROLE_DIRECTOR].id,
        invoice_number=f"INV-{due_offset}-{amount}", invoice_date=TODAY,
        amount_try=Decimal(amount), vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amount),
        net_due_try=Decimal(amount), due_date=TODAY + timedelta(days=due_offset),
        payment_status="unpaid", **kw,
    )


def test_windows_accumulate_and_flag_shortfall(db, seed):
    a = seed["a"]
    db.add_all([
        _cost(a, 20, "100000"),   # due in 30d window
        _cost(a, 50, "40000"),    # due in 60d window
        _cost(a, 80, "10000"),    # due in 90d window
        _inv(a, 20, "30000"),     # collection in 30d window
        _cost(a, 200, "999999"),  # outside 90d -> excluded
    ])
    db.commit()

    w = {x["days"]: x for x in cash_need_windows(db, a["project"], today=TODAY)}
    assert w[30]["planned_out_try"] == "100000.00"
    assert w[30]["expected_in_try"] == "30000.00"
    assert w[30]["net_need_try"] == "70000.00"
    assert w[30]["shortfall"] is True
    # 60-day window includes the 30-day items plus the 50-day cost.
    assert w[60]["planned_out_try"] == "140000.00"
    assert w[90]["planned_out_try"] == "150000.00"


def test_surplus_is_not_shortfall(db, seed):
    a = seed["a"]
    db.add_all([_cost(a, 10, "10000"), _inv(a, 10, "50000")])
    db.commit()
    w = {x["days"]: x for x in cash_need_windows(db, a["project"], today=TODAY)}
    assert w[30]["net_need_try"] == "-40000.00"
    assert w[30]["shortfall"] is False


def test_pending_and_paid_costs_excluded(db, seed):
    a = seed["a"]
    db.add_all([
        _cost(a, 10, "5000", pending_approval=True),
        _cost(a, 10, "5000", payment_status="paid"),
    ])
    db.commit()
    w = {x["days"]: x for x in cash_need_windows(db, a["project"], today=TODAY)}
    assert w[30]["planned_out_try"] == "0.00"
