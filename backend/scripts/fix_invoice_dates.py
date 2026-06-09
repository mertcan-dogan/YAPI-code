"""CR-003-C data repair: backfill client_invoices.date_received.

Paid invoices whose date_received is NULL never appear in the cash-flow income
column. This sets date_received = due_date (best estimate) for any invoice that
is paid but missing its collection date.

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


def backfill_invoice_dates(db: Session, apply: bool = True) -> int:
    """Set date_received = due_date for paid invoices missing date_received.
    Returns the number of affected rows."""
    rows = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.payment_status == "paid",
            ClientInvoice.date_received.is_(None),
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalars().all()
    for inv in rows:
        if apply:
            inv.date_received = inv.due_date
    if apply:
        db.flush()
    return len(rows)


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        n = backfill_invoice_dates(db, apply=not dry)
        if dry:
            print(f"[DRY-RUN] {n} fatura için date_received = due_date atanacak.")
        else:
            db.commit()
            print(f"[DONE] {n} fatura güncellendi (date_received = due_date).")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
