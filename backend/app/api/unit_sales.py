"""Unit sales (daire satış kaydı) router (CR-031-A).

Company-scoped CRUD over ``unit_sales`` + the per-unit cost-allocation P&L view.
FX-at-date auto-fill on create/update (CR-014 pattern). Soft-delete on remove.
Cost is read-only here — per-unit cost is an allocation VIEW, never a cost row.
"""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, InvoiceCreatorUser
from app.models.unit_sale import UnitSale
from app.responses import APIError, success
from app.schemas.unit_sale import UnitSaleCreate, UnitSaleOut, UnitSaleUpdate
from app.services import fx
from app.services import sales as sales_service
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["unit-sales"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_sale(db: Session, project_id: uuid.UUID, sale_id: uuid.UUID) -> UnitSale:
    sale = db.execute(
        select(UnitSale).where(
            UnitSale.id == sale_id,
            UnitSale.project_id == project_id,
            UnitSale.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if sale is None:
        raise APIError(404, "NOT_FOUND", "Satış kaydı bulunamadı")
    return sale


@router.get("/projects/{project_id}/unit-sales")
def list_unit_sales(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Sales list each with derived cost/pnl/margin + a totals row (§1.2)."""
    project = get_company_project(db, project_id, user)
    return success(sales_service.unit_sales_pnl(db, project))


@router.post("/projects/{project_id}/unit-sales")
def create_unit_sale(
    project_id: uuid.UUID,
    payload: UnitSaleCreate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    sale = UnitSale(
        project_id=project.id,
        company_id=user.company_id,
        created_by=user.id,
        **payload.model_dump(),
    )
    db.add(sale)
    db.flush()
    # CR-014 pattern: snapshot USD at the sale_date (TRY ÷ rate@sale_date).
    fx.snapshot_unit_sale_usd(db, sale)
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="unit_sales",
        record_id=sale.id, action="INSERT", new_values=snapshot(sale), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(sale)
    return success(UnitSaleOut.model_validate(sale).model_dump(mode="json"))


@router.put("/projects/{project_id}/unit-sales/{sale_id}")
def update_unit_sale(
    project_id: uuid.UUID,
    sale_id: uuid.UUID,
    payload: UnitSaleUpdate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    sale = _get_sale(db, project.id, sale_id)
    old = snapshot(sale)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(sale, k, v)
    # Re-snapshot USD when price or date changed (or when no snapshot exists yet).
    if {"sale_price_try", "sale_date"} & set(changes) or sale.sale_price_usd is None:
        fx.snapshot_unit_sale_usd(db, sale)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="unit_sales",
        record_id=sale.id, action="UPDATE", old_values=old, new_values=snapshot(sale),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(sale)
    return success(UnitSaleOut.model_validate(sale).model_dump(mode="json"))


@router.delete("/projects/{project_id}/unit-sales/{sale_id}")
def delete_unit_sale(
    project_id: uuid.UUID,
    sale_id: uuid.UUID,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    project = get_company_project(db, project_id, user)
    sale = _get_sale(db, project.id, sale_id)
    old = snapshot(sale)
    sale.is_deleted = True
    sale.deleted_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="unit_sales",
        record_id=sale.id, action="DELETE", old_values=old, new_values=snapshot(sale),
        ip_address=_ip(request),
    )
    db.commit()
    return success({"id": str(sale_id), "deleted": True})
