"""Payment reminders router — cross-project payables & receivables (Section 4.7)."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.responses import success

router = APIRouter(tags=["reminders"])


def _days_label(days_remaining: int) -> str:
    if days_remaining < 0:
        return f"{abs(days_remaining)} gün gecikti"
    if days_remaining == 0:
        return "Bugün"
    return f"{days_remaining} gün kaldı"


# CR-002-C: exhaustive colour rules (border + background).
def _colours(days_remaining: int, paid: bool) -> tuple[str, str]:
    if paid:
        return "#10B981", "#F0FDF4"  # green
    if days_remaining <= 0:
        return "#EF4444", "#FEF2F2"  # overdue OR due today -> red
    if days_remaining <= 7:
        return "#F59E0B", "#FFFBEB"  # amber
    if days_remaining <= 30:
        return "#EAB308", "#FEFCE8"  # yellow
    if days_remaining <= 60:
        return "#93C5FD", "#EFF6FF"  # light blue
    return "#E2E8F0", "#FFFFFF"


def _border_colour(days_remaining: int, paid: bool) -> str:
    return _colours(days_remaining, paid)[0]


@router.get("/reminders")
def list_reminders(user: CurrentUser, db: Session = Depends(get_db)):
    today = date.today()
    project_names = {
        p.id: p.name
        for p in db.execute(
            select(Project).where(
                Project.company_id == user.company_id, Project.is_deleted.is_(False)
            )
        ).scalars().all()
    }

    items: list[dict] = []

    # Payables — unpaid/partial cost entries with a due date.
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.company_id == user.company_id,
            CostEntry.is_deleted.is_(False),
            CostEntry.payment_status != "paid",
            CostEntry.payment_due_date.isnot(None),
            CostEntry.entry_type != "forecast",
        )
    ).scalars().all()
    for c in costs:
        days = (c.payment_due_date - today).days
        items.append(
            {
                "kind": "payable",
                "project_id": str(c.project_id),
                "project_name": project_names.get(c.project_id, ""),
                "party": c.supplier_name or "—",
                "description": c.description or c.cost_category,
                "amount_try": str(c.total_with_vat_try),
                "due_date": c.payment_due_date.isoformat(),
                "days_remaining": days,
                "days_label": _days_label(days),
                "border_colour": _colours(days, False)[0],
                "bg_colour": _colours(days, False)[1],
                "status": c.payment_status,
                "record_id": str(c.id),
            }
        )

    # Receivables — unpaid/partial client invoices.
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.company_id == user.company_id,
            ClientInvoice.is_deleted.is_(False),
            ClientInvoice.payment_status != "paid",
        )
    ).scalars().all()
    for inv in invoices:
        if inv.outstanding_try <= 0:
            continue
        days = (inv.due_date - today).days
        items.append(
            {
                "kind": "receivable",
                "project_id": str(inv.project_id),
                "project_name": project_names.get(inv.project_id, ""),
                "party": inv.hakkedis_period or inv.invoice_number,
                "description": inv.description or f"Hakediş {inv.invoice_number}",
                "amount_try": str(inv.outstanding_try),
                "net_due_try": str(inv.net_due_try),  # CR-004-D: full amount for "Tahsil Edildi"
                "due_date": inv.due_date.isoformat(),
                "days_remaining": days,
                "days_label": _days_label(days),
                "border_colour": _colours(days, False)[0],
                "bg_colour": _colours(days, False)[1],
                "status": inv.payment_status,
                "record_id": str(inv.id),
            }
        )

    items.sort(key=lambda i: i["due_date"])
    return success(items, meta={"total": len(items)})
