"""CR-004-B: dashboard combined cash flow (last 6 months) shows real data."""
from datetime import date
from decimal import Decimal

from app.api.projects import _combined_cashflow_chart, _last_n_months
from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry

ANCHOR = date(2026, 6, 10)


def _cost(project, company, user, d: date, total: str, **kw):
    return CostEntry(
        project_id=project.id, company_id=company.id, created_by=user.id,
        entry_date=d, cost_category="materials", amount_try=Decimal(total),
        total_with_vat_try=Decimal(total), **kw,
    )


def _invoice(project, company, user, received: date | None, amount: str, **kw):
    return ClientInvoice(
        project_id=project.id, company_id=company.id, created_by=user.id,
        invoice_number=f"INV-{received}-{amount}", invoice_date=date(2026, 1, 1),
        amount_try=Decimal(amount), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal(amount), net_due_try=Decimal(amount),
        due_date=date(2026, 2, 1), date_received=received,
        amount_received_try=Decimal(amount) if received else Decimal("0"),
        payment_status="paid" if received else "unpaid", **kw,
    )


def test_last_n_months_window():
    assert _last_n_months(6, ANCHOR) == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
    ]


def test_combined_cashflow_sums_expense_and_income(db, seed):
    a = seed["a"]
    project, company = a["project"], a["company"]
    user = a["users"][ROLE_DIRECTOR]

    db.add_all([
        _cost(project, company, user, date(2026, 3, 15), "120000"),
        _cost(project, company, user, date(2026, 3, 20), "30000"),
        _invoice(project, company, user, date(2026, 3, 10), "50000"),
        # Outside the 6-month window — must be excluded.
        _cost(project, company, user, date(2025, 6, 1), "999999"),
        # Pending-approval cost must be excluded.
        _cost(project, company, user, date(2026, 4, 1), "777777", pending_approval=True),
    ])
    db.commit()

    chart = _combined_cashflow_chart(db, [project.id], anchor=ANCHOR)
    assert [c["month"] for c in chart] == _last_n_months(6, ANCHOR)

    march = next(c for c in chart if c["month"] == "2026-03")
    assert march["out"] == "150000.00"
    assert march["in"] == "50000.00"

    april = next(c for c in chart if c["month"] == "2026-04")
    assert april["out"] == "0.00"  # pending-approval cost excluded

    # Net cumulative carries forward: March net = 50000 - 150000 = -100000.
    assert march["net_cumulative"] == "-100000.00"


def test_combined_cashflow_empty_when_no_projects(db):
    chart = _combined_cashflow_chart(db, [], anchor=ANCHOR)
    assert len(chart) == 6
    assert all(c["out"] == "0.00" and c["in"] == "0.00" for c in chart)
