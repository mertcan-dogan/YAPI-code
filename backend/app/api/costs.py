"""Cost entries router (Section 2.5, 4.3, 3.2)."""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calculations.money import D
from app.constants import (
    ROLE_DIRECTOR,
    ROLE_FINANCE,
    ROLE_PROJECT_MANAGER,
    ROLE_SITE_MANAGER,
)
from app.db import get_db
from app.deps import CurrentUser
from app.models.cost_entry import CostEntry
from app.responses import APIError, success
from app.schemas.cost import CostEntryCreate, CostEntryOut, CostEntryUpdate
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import total_with_vat, vat_amount

router = APIRouter(tags=["costs"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _refresh_payment_status(c: CostEntry, today: date | None = None) -> None:
    """Keep payment_status coherent with amounts/dates (overdue is derived)."""
    today = today or date.today()
    if c.amount_paid_try and c.amount_paid_try >= c.total_with_vat_try:
        c.payment_status = "paid"
    elif c.amount_paid_try and c.amount_paid_try > 0:
        c.payment_status = "partial"
    elif c.payment_due_date and c.payment_due_date < today:
        c.payment_status = "overdue"
    else:
        c.payment_status = "unpaid"


@router.get("/projects/{project_id}/costs")
def list_costs(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    category: str | None = None,
    payment_status: str | None = None,
    entry_type: str | None = None,
    supplier: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    project = get_company_project(db, project_id, user)
    stmt = select(CostEntry).where(
        CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False)
    )
    if category:
        stmt = stmt.where(CostEntry.cost_category == category)
    if payment_status:
        stmt = stmt.where(CostEntry.payment_status == payment_status)
    if entry_type:
        stmt = stmt.where(CostEntry.entry_type == entry_type)
    if supplier:
        stmt = stmt.where(CostEntry.supplier_name.ilike(f"%{supplier}%"))
    if date_from:
        stmt = stmt.where(CostEntry.entry_date >= date_from)
    if date_to:
        stmt = stmt.where(CostEntry.entry_date <= date_to)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(CostEntry.entry_date.desc(), CostEntry.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()
    data = [CostEntryOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success(data, meta={"total": total, "page": page, "per_page": per_page})


@router.post("/projects/{project_id}/costs")
def create_cost(
    project_id: uuid.UUID,
    payload: CostEntryCreate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)  # all roles may add (Section 3.2)
    data = payload.model_dump()
    vat = vat_amount(data["amount_try"], data["vat_rate"])
    twv = total_with_vat(data["amount_try"], data["vat_rate"])
    cost = CostEntry(
        project_id=project.id,
        company_id=user.company_id,
        created_by=user.id,
        vat_amount_try=vat,
        total_with_vat_try=twv,
        **data,
    )
    _refresh_payment_status(cost)
    db.add(cost)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="INSERT", new_values=snapshot(cost), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(cost)
    return success(CostEntryOut.model_validate(cost).model_dump(mode="json"))


def _get_cost(db: Session, project, cost_id: uuid.UUID) -> CostEntry:
    cost = db.execute(
        select(CostEntry).where(
            CostEntry.id == cost_id,
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if cost is None:
        raise APIError(404, "NOT_FOUND", "Maliyet kaydı bulunamadı")
    return cost


@router.put("/projects/{project_id}/costs/{cost_id}")
def update_cost(
    project_id: uuid.UUID,
    cost_id: uuid.UUID,
    payload: CostEntryUpdate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    cost = _get_cost(db, project, cost_id)

    # Edit permissions (Section 3.2): PM/Site may edit own only.
    if user.role in (ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER) and cost.created_by != user.id:
        raise APIError(403, "FORBIDDEN", "Yalnızca kendi girişlerinizi düzenleyebilirsiniz")

    old = snapshot(cost)
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(cost, k, v)
    # Recompute derived VAT fields.
    cost.vat_amount_try = vat_amount(cost.amount_try, cost.vat_rate)
    cost.total_with_vat_try = total_with_vat(cost.amount_try, cost.vat_rate)
    cost.last_modified_by = user.id
    if "date_paid" in changes and cost.date_paid and not cost.amount_paid_try:
        cost.amount_paid_try = cost.total_with_vat_try
    _refresh_payment_status(cost)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="UPDATE", old_values=old, new_values=snapshot(cost),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(cost)
    return success(CostEntryOut.model_validate(cost).model_dump(mode="json"))


@router.delete("/projects/{project_id}/costs/{cost_id}")
def delete_cost(
    project_id: uuid.UUID,
    cost_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    # Only directors may delete cost entries (Section 3.2).
    if user.role != ROLE_DIRECTOR:
        raise APIError(403, "FORBIDDEN", "Maliyet kaydını yalnızca yönetici silebilir")
    project = get_company_project(db, project_id, user)
    cost = _get_cost(db, project, cost_id)
    old = snapshot(cost)
    cost.is_deleted = True
    cost.deleted_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="DELETE", old_values=old, ip_address=_ip(request),
    )
    db.commit()
    return success({"id": str(cost_id), "message": "Maliyet kaydı silindi"})
