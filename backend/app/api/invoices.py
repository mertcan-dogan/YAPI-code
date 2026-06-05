"""Client invoices (Hakediş) router (Section 2.5, 4.4, 3.2)."""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE
from app.db import get_db
from app.deps import CurrentUser, InvoiceCreatorUser
from app.models.client_invoice import ClientInvoice
from app.responses import APIError, success
from app.schemas.invoice import ClientInvoiceCreate, ClientInvoiceOut, ClientInvoiceUpdate
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import invoice_net_due, total_with_vat, vat_amount

router = APIRouter(tags=["invoices"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _refresh_invoice_status(inv: ClientInvoice, today: date | None = None) -> None:
    today = today or date.today()
    if inv.amount_received_try >= inv.net_due_try and inv.net_due_try > 0:
        inv.payment_status = "paid"
    elif inv.amount_received_try and inv.amount_received_try > 0:
        inv.payment_status = "partial"
    else:
        inv.payment_status = "unpaid"


@router.get("/projects/{project_id}/invoices")
def list_invoices(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = db.execute(
        select(ClientInvoice)
        .where(ClientInvoice.project_id == project.id, ClientInvoice.is_deleted.is_(False))
        .order_by(ClientInvoice.invoice_date.desc())
    ).scalars().all()
    data = [ClientInvoiceOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success(data, meta={"total": len(data)})


@router.post("/projects/{project_id}/invoices")
def create_invoice(
    project_id: uuid.UUID,
    payload: ClientInvoiceCreate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    data = payload.model_dump()
    vat = vat_amount(data["amount_try"], data["vat_rate"])
    twv = total_with_vat(data["amount_try"], data["vat_rate"])
    net_due = invoice_net_due(data["amount_try"], data["vat_rate"], data["retention_amount_try"])
    inv = ClientInvoice(
        project_id=project.id,
        company_id=user.company_id,
        created_by=user.id,
        vat_amount_try=vat,
        total_with_vat_try=twv,
        net_due_try=net_due,
        amount_received_try=0,
        payment_status="unpaid",
        **data,
    )
    db.add(inv)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Unique (project_id, invoice_number) violation (Section 8.1)
        raise APIError(422, "VALIDATION_ERROR", "Bu fatura numarası zaten mevcut", field="invoice_number")
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="client_invoices",
        record_id=inv.id, action="INSERT", new_values=snapshot(inv), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(inv)
    return success(ClientInvoiceOut.model_validate(inv).model_dump(mode="json"))


@router.put("/projects/{project_id}/invoices/{inv_id}")
def update_invoice(
    project_id: uuid.UUID,
    inv_id: uuid.UUID,
    payload: ClientInvoiceUpdate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    inv = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.id == inv_id,
            ClientInvoice.project_id == project.id,
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if inv is None:
        raise APIError(404, "NOT_FOUND", "Fatura bulunamadı")

    changes = payload.model_dump(exclude_unset=True)
    # Marking an invoice paid/received is restricted to Director & Finance (Section 3.2).
    money_fields = {"date_received", "amount_received_try", "payment_status"}
    if money_fields & set(changes) and user.role not in (ROLE_DIRECTOR, ROLE_FINANCE):
        raise APIError(403, "FORBIDDEN", "Tahsilat işlemini yalnızca yönetici veya muhasebe yapabilir")

    old = snapshot(inv)
    for k, v in changes.items():
        setattr(inv, k, v)
    inv.vat_amount_try = vat_amount(inv.amount_try, inv.vat_rate)
    inv.total_with_vat_try = total_with_vat(inv.amount_try, inv.vat_rate)
    inv.net_due_try = invoice_net_due(inv.amount_try, inv.vat_rate, inv.retention_amount_try)
    if "date_received" in changes and inv.date_received and not inv.amount_received_try:
        inv.amount_received_try = inv.net_due_try
    if "payment_status" not in changes:
        _refresh_invoice_status(inv)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="client_invoices",
        record_id=inv.id, action="UPDATE", old_values=old, new_values=snapshot(inv),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(inv)
    return success(ClientInvoiceOut.model_validate(inv).model_dump(mode="json"))
