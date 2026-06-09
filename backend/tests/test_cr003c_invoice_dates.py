"""CR-003-C: backfill date_received for paid invoices."""
import sys
from datetime import date

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "scripts")

from scripts.fix_invoice_dates import backfill_invoice_dates  # noqa: E402

from app.models.client_invoice import ClientInvoice


def _paid_invoice(db, seed, **over):
    a = seed["a"]
    inv = ClientInvoice(
        project_id=a["project"].id, company_id=a["company"].id,
        invoice_number=over.get("invoice_number", "HAK-C1"), invoice_date=date(2026, 1, 1),
        amount_try=100000, vat_amount_try=0, total_with_vat_try=100000, net_due_try=100000,
        amount_received_try=100000, payment_status="paid", due_date=date(2026, 2, 1),
        date_received=over.get("date_received"), created_by=a["users"]["director"].id,
    )
    db.add(inv)
    db.flush()
    return inv


def test_backfill_sets_date_received_to_due_date(db, seed):
    inv = _paid_invoice(db, seed, date_received=None)
    assert inv.date_received is None
    n = backfill_invoice_dates(db, apply=True)
    assert n == 1
    db.refresh(inv)
    assert inv.date_received == date(2026, 2, 1)


def test_backfill_leaves_existing_dates_untouched(db, seed):
    inv = _paid_invoice(db, seed, invoice_number="HAK-C2", date_received=date(2026, 1, 20))
    backfill_invoice_dates(db, apply=True)
    db.refresh(inv)
    assert inv.date_received == date(2026, 1, 20)  # unchanged


def test_dry_run_does_not_modify(db, seed):
    inv = _paid_invoice(db, seed, invoice_number="HAK-C3", date_received=None)
    n = backfill_invoice_dates(db, apply=False)
    assert n == 1
    db.refresh(inv)
    assert inv.date_received is None  # preview only
