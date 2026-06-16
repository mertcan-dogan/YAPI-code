"""CR-014-B: one-time USD snapshot backfill (mirrors the vendor backfill).

Populates ``fx_rate_usd`` + ``amount_usd`` for existing ``cost_entries`` and
``client_invoices`` from historical TCMB rates at each row's relevant date
(date_paid/date_received if paid, else entry_date/invoice_date — §2.2).

Conservative + idempotent:
  - Skips rows already populated (``fx_rate_usd`` not null) — safe to re-run.
  - Rows whose relevant date predates available TCMB history (rate_as_of -> None)
    are left null and counted as ``*_no_rate`` (flagged), never erroring.
  - TRY columns are never touched.

Run as an EXPLICIT one-time step after deploy (like the vendor backfill), NOT on
boot, e.g. ``backfill_all_companies(db)``.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services import fx

logger = logging.getLogger("yapi.fx_backfill")


def backfill_company(db: Session, company_id) -> dict:
    """Idempotent USD backfill for one company. Returns a summary of what changed."""
    summary = {
        "costs_updated": 0, "costs_skipped": 0, "costs_no_rate": 0,
        "invoices_updated": 0, "invoices_skipped": 0, "invoices_no_rate": 0,
    }

    costs = db.execute(
        select(CostEntry).where(
            CostEntry.company_id == company_id, CostEntry.is_deleted.is_(False)
        )
    ).scalars().all()
    for c in costs:
        if c.fx_rate_usd is not None:
            summary["costs_skipped"] += 1
            continue
        if fx.snapshot_cost_usd(db, c):
            summary["costs_updated"] += 1
        else:
            summary["costs_no_rate"] += 1  # pre-history / no rate — left null, flagged

    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.company_id == company_id, ClientInvoice.is_deleted.is_(False)
        )
    ).scalars().all()
    for inv in invoices:
        if inv.fx_rate_usd is not None:
            summary["invoices_skipped"] += 1
            continue
        if fx.snapshot_invoice_usd(db, inv):
            summary["invoices_updated"] += 1
        else:
            summary["invoices_no_rate"] += 1

    db.commit()
    logger.info(
        "[fx_backfill] company=%s costs(updated=%d skipped=%d no_rate=%d) "
        "invoices(updated=%d skipped=%d no_rate=%d)",
        company_id, summary["costs_updated"], summary["costs_skipped"], summary["costs_no_rate"],
        summary["invoices_updated"], summary["invoices_skipped"], summary["invoices_no_rate"],
    )
    return summary


def backfill_all_companies(db: Session) -> dict[str, dict]:
    """Run the USD backfill for every company — the explicit post-deploy step."""
    from app.models.company import Company

    results: dict[str, dict] = {}
    for c in db.execute(select(Company)).scalars().all():
        results[str(c.id)] = backfill_company(db, c.id)
    return results
