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
from app.services import fx
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import total_with_vat, vat_amount

router = APIRouter(tags=["costs"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _bump_custom_category(db: Session, company_id, category: str) -> None:
    """If a cost uses a company custom category, increment its usage_count (CR-001-D)."""
    from app.constants import COST_CATEGORY_KEYS
    from app.models.custom_category import CustomCostCategory

    if not category or category in COST_CATEGORY_KEYS:
        return
    norm = " ".join(category.strip().lower().split())
    cat = db.execute(
        select(CustomCostCategory).where(
            CustomCostCategory.company_id == company_id,
            CustomCostCategory.name_normalized == norm,
            CustomCostCategory.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if cat is not None:
        cat.usage_count = (cat.usage_count or 0) + 1


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
    # CR-003-J: entries above the company threshold await director approval and are
    # excluded from the dashboard until approved.
    from app.models.company import Company

    company = db.get(Company, user.company_id)
    if company and company.approvals_enabled and D(cost.amount_try) > D(company.cost_approval_threshold_try):
        cost.pending_approval = True
    _refresh_payment_status(cost)
    db.add(cost)
    db.flush()
    # CR-014-B: snapshot the USD value at this row's relevant date (provisional
    # until paid). Never blocks the save if no rate is available.
    fx.snapshot_cost_usd(db, cost)
    _bump_custom_category(db, user.company_id, cost.cost_category)
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="INSERT", new_values=snapshot(cost), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(cost)
    _notify_margin(db, project)
    return success(CostEntryOut.model_validate(cost).model_dump(mode="json"))


def _notify_margin(db: Session, project) -> None:
    """CR-006-B/C: cost değişikliği sonrası marj e-postası + uygulama içi bildirimler."""
    try:
        from app.services.triggers import check_margin_warning, notify_cost_change

        check_margin_warning(db, project)        # CR-006-B: e-posta (<%5)
        notify_cost_change(db, project)          # CR-006-C: zil bildirimleri (<%10, bütçe %95)
    except Exception:  # tetikleyici hiçbir koşulda isteği bozmamalı
        pass


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
    # CR-014-B: re-snapshot USD — locks at the payment-date rate once paid.
    fx.snapshot_cost_usd(db, cost)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="UPDATE", old_values=old, new_values=snapshot(cost),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(cost)
    _notify_margin(db, project)
    return success(CostEntryOut.model_validate(cost).model_dump(mode="json"))


@router.delete("/projects/{project_id}/costs/{cost_id}")
def delete_cost(
    project_id: uuid.UUID,
    cost_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    # CR-001-G: Director and Project Manager may soft-delete cost entries.
    if user.role not in (ROLE_DIRECTOR, ROLE_PROJECT_MANAGER):
        raise APIError(403, "FORBIDDEN", "Maliyet kaydını yalnızca yönetici veya proje müdürü silebilir")
    project = get_company_project(db, project_id, user)
    cost = _get_cost(db, project, cost_id)

    # CR-004-N: deletions may require director approval first.
    from app.models.company import Company
    from app.services import approvals as approvals_service

    company = db.get(Company, user.company_id)
    if approvals_service.is_required(company, "cost_deletion"):
        approvals_service.create_request(
            db, company_id=user.company_id, project_id=project.id,
            kind="cost_deletion", target_table="cost_entries", target_id=cost.id,
            payload=None, description=cost.description or cost.cost_category,
            amount_try=cost.total_with_vat_try, requested_by=user.id,
        )
        db.commit()
        return success({"id": str(cost_id), "pending_approval": True, "message": "Silme işlemi onaya gönderildi"})

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
