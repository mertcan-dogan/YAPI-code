"""Landowner payments (arsa sahibi ödeme defteri) router (CR-031-B).

Company-scoped CRUD over ``landowner_payments`` + the SQL-side ledger rollup
(Σ TRY/USD, count, remaining-vs-committed). FX-at-date auto-fill on create/update
(CR-014 pattern). Soft-delete on remove. Part of sell-side revenue — never feeds
hakediş. The API always works; the UI hides it for non-share models (§2.2/§5).
"""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, InvoiceCreatorUser
from app.models.landowner_payment import LandownerPayment
from app.responses import APIError, success
from app.schemas.landowner_payment import (
    LandownerPaymentCreate,
    LandownerPaymentOut,
    LandownerPaymentUpdate,
)
from app.services import fx
from app.services import sales as sales_service
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["landowner-payments"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_payment(db: Session, project_id: uuid.UUID, payment_id: uuid.UUID) -> LandownerPayment:
    p = db.execute(
        select(LandownerPayment).where(
            LandownerPayment.id == payment_id,
            LandownerPayment.project_id == project_id,
            LandownerPayment.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if p is None:
        raise APIError(404, "NOT_FOUND", "Arsa sahibi ödemesi bulunamadı")
    return p


@router.get("/projects/{project_id}/landowner-payments")
def list_landowner_payments(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Payments list + SQL rollup (Σ TRY/USD, count, remaining-vs-committed)."""
    project = get_company_project(db, project_id, user)
    return success(sales_service.landowner_ledger(db, project))


@router.post("/projects/{project_id}/landowner-payments")
def create_landowner_payment(
    project_id: uuid.UUID,
    payload: LandownerPaymentCreate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    p = LandownerPayment(
        project_id=project.id,
        company_id=user.company_id,
        created_by=user.id,
        **payload.model_dump(),
    )
    db.add(p)
    db.flush()
    # CR-014 pattern: snapshot USD at the payment_date (TRY ÷ rate@payment_date).
    fx.snapshot_landowner_payment_usd(db, p)
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="landowner_payments",
        record_id=p.id, action="INSERT", new_values=snapshot(p), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(p)
    return success(LandownerPaymentOut.model_validate(p).model_dump(mode="json"))


@router.put("/projects/{project_id}/landowner-payments/{payment_id}")
def update_landowner_payment(
    project_id: uuid.UUID,
    payment_id: uuid.UUID,
    payload: LandownerPaymentUpdate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    p = _get_payment(db, project.id, payment_id)
    old = snapshot(p)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    if {"amount_try", "payment_date"} & set(changes) or p.amount_usd is None:
        fx.snapshot_landowner_payment_usd(db, p)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="landowner_payments",
        record_id=p.id, action="UPDATE", old_values=old, new_values=snapshot(p),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(p)
    return success(LandownerPaymentOut.model_validate(p).model_dump(mode="json"))


@router.delete("/projects/{project_id}/landowner-payments/{payment_id}")
def delete_landowner_payment(
    project_id: uuid.UUID,
    payment_id: uuid.UUID,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    project = get_company_project(db, project_id, user)
    p = _get_payment(db, project.id, payment_id)
    old = snapshot(p)
    p.is_deleted = True
    p.deleted_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="landowner_payments",
        record_id=p.id, action="DELETE", old_values=old, new_values=snapshot(p),
        ip_address=_ip(request),
    )
    db.commit()
    return success({"id": str(payment_id), "deleted": True})
