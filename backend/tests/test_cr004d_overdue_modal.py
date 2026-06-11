"""CR-004-D: overdue drill-down modal data contract (reminders endpoint)."""
from datetime import date, timedelta
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice


def test_receivable_reminder_exposes_net_due_for_collection(client, db, seed):
    a = seed["a"]
    inv = ClientInvoice(
        project_id=a["project"].id, company_id=a["company"].id,
        invoice_number="HAK-OVD", invoice_date=date(2026, 1, 1),
        amount_try=Decimal("100000"), vat_amount_try=Decimal("20000"),
        total_with_vat_try=Decimal("120000"), net_due_try=Decimal("110000"),
        amount_received_try=Decimal("0"), payment_status="unpaid",
        due_date=date.today() - timedelta(days=10), created_by=a["users"][ROLE_DIRECTOR].id,
    )
    db.add(inv)
    db.commit()

    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/reminders")
    assert r.status_code == 200, r.text
    receivables = [i for i in r.json()["data"] if i["kind"] == "receivable"]
    assert receivables, "expected at least one receivable reminder"
    item = next(i for i in receivables if i["record_id"] == str(inv.id))
    assert item["net_due_try"] == "110000.00"
    assert item["days_remaining"] < 0  # overdue -> appears in the modal
