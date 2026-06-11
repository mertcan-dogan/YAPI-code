"""CR-004-C: fix collections wrongly clustered on due_date; audit each change."""
import sys
from datetime import date

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "scripts")

from scripts.fix_invoice_dates import backfill_invoice_dates  # noqa: E402

from app.models.audit_log import AuditLog
from app.models.client_invoice import ClientInvoice


def _paid(db, seed, num, invoice_date, due_date, date_received):
    a = seed["a"]
    inv = ClientInvoice(
        project_id=a["project"].id, company_id=a["company"].id,
        invoice_number=num, invoice_date=invoice_date,
        amount_try=100000, vat_amount_try=0, total_with_vat_try=100000, net_due_try=100000,
        amount_received_try=100000, payment_status="paid",
        due_date=due_date, date_received=date_received,
        created_by=a["users"]["director"].id,
    )
    db.add(inv)
    db.flush()
    return inv


def test_stale_due_date_corrected_to_invoice_period(db, seed):
    # The original CR-003-C repair pinned both collections to their June due_date.
    jan = _paid(db, seed, "AVANS", date(2026, 1, 5), date(2026, 6, 1), date(2026, 6, 1))
    feb = _paid(db, seed, "HAK-001", date(2026, 2, 10), date(2026, 6, 1), date(2026, 6, 1))

    n = backfill_invoice_dates(db, apply=True)
    assert n == 2
    db.refresh(jan)
    db.refresh(feb)
    assert jan.date_received == date(2026, 1, 5)   # Ocak avans -> Ocak
    assert feb.date_received == date(2026, 2, 10)  # HAK-001 -> Şubat


def test_each_change_is_audited(db, seed):
    _paid(db, seed, "AVANS", date(2026, 1, 5), date(2026, 6, 1), date(2026, 6, 1))
    backfill_invoice_dates(db, apply=True)
    db.flush()
    logs = db.query(AuditLog).filter(AuditLog.table_name == "client_invoices").all()
    assert len(logs) == 1
    assert logs[0].new_values["date_received"] == "2026-01-05"
    assert logs[0].old_values["date_received"] == "2026-06-01"


def test_due_date_equal_to_period_is_left_alone(db, seed):
    # If due_date already matches the invoice period, nothing to fix.
    inv = _paid(db, seed, "OK", date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 1))
    n = backfill_invoice_dates(db, apply=True)
    assert n == 0
    db.refresh(inv)
    assert inv.date_received == date(2026, 3, 1)
