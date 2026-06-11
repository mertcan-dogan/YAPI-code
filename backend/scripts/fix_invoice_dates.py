"""CR-003-C / CR-004-C data repair: fix client_invoices.date_received.

A paid invoice only appears in the cash-flow income column in the month of its
``date_received``. Two problems are repaired here:

  1. date_received IS NULL  → the invoice never shows up at all.
  2. date_received was bulk-set to ``due_date`` by the original CR-003-C repair,
     and the live due-dates all cluster in one month (June) — so every collection
     wrongly lands in June (CR-004-C symptom).

Both are corrected to the invoice's own ``invoice_date`` (the hakediş period),
which is the accurate month the revenue belongs to — so the Ocak avans shows in
Ocak, HAK-001 in Şubat, etc. (The CR suggested ``created_at`` as a fallback, but
that is the row-insertion timestamp and clusters at import time; ``invoice_date``
is the real period.) Every change is written to the audit log.

Run from backend/ with .env populated:

    python scripts/fix_invoice_dates.py            # apply
    python scripts/fix_invoice_dates.py --dry-run  # preview only
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.client_invoice import ClientInvoice
from app.services.audit import record_audit


def _target_date(inv: ClientInvoice):
    """The month the collection truly belongs to: the invoice/hakediş period."""
    if inv.invoice_date:
        return inv.invoice_date
    if inv.created_at:
        return inv.created_at.date()
    return inv.due_date


def backfill_invoice_dates(db: Session, apply: bool = True, user_id=None) -> int:
    """Repair date_received for paid invoices. Returns the number of rows changed.

    A row is changed when date_received is missing, or when it was left equal to
    due_date by the original repair while the real period (invoice_date) differs.
    Rows a user set to a genuine collection date are left untouched.
    """
    rows = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.payment_status == "paid",
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalars().all()

    changed = 0
    for inv in rows:
        target = _target_date(inv)
        if target is None:
            continue
        current = inv.date_received
        is_null = current is None
        is_stale_due_date = current is not None and current == inv.due_date and current != target
        if not (is_null or is_stale_due_date):
            continue
        if current == target:
            continue

        old = {"date_received": current.isoformat() if current else None}
        if apply:
            inv.date_received = target
            record_audit(
                db,
                company_id=inv.company_id,
                user_id=user_id,
                table_name="client_invoices",
                record_id=inv.id,
                action="update",
                old_values=old,
                new_values={"date_received": target.isoformat()},
            )
        changed += 1

    if apply:
        db.flush()
    return changed


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        n = backfill_invoice_dates(db, apply=not dry)
        if dry:
            print(f"[DRY-RUN] {n} fatura için date_received = invoice_date olarak düzeltilecek.")
        else:
            db.commit()
            print(f"[DONE] {n} fatura güncellendi (date_received = invoice_date) ve audit log'a yazıldı.")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
