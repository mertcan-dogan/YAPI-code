"""Variations / Ek İş router (CR-003-I)."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.db import get_db
from app.deps import CurrentUser, InvoiceCreatorUser
from app.models.budget_line_item import BudgetLineItem
from app.models.variation import Variation
from app.responses import APIError, success
from app.schemas.variation import VariationCreate, VariationOut, VariationUpdate
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["variations"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _sync_category_budget(db: Session, project_id, company_id, cost_category: str | None) -> None:
    """CR-003-I: budget_line_items.approved_variations_try for a category =
    SUM of approved variations' approved_value for that category."""
    if not cost_category:
        return
    total = money(sum(
        (D(v.approved_value_try) for v in db.execute(
            select(Variation).where(
                Variation.project_id == project_id,
                Variation.cost_category == cost_category,
                Variation.status == "approved",
                Variation.is_deleted.is_(False),
            )
        ).scalars().all() if v.approved_value_try is not None),
        D(0),
    ))
    line = db.execute(
        select(BudgetLineItem).where(
            BudgetLineItem.project_id == project_id,
            BudgetLineItem.cost_category == cost_category,
            BudgetLineItem.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if line is None:
        line = BudgetLineItem(project_id=project_id, company_id=company_id, cost_category=cost_category)
        db.add(line)
    line.approved_variations_try = total


@router.get("/projects/{project_id}/variations")
def list_variations(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = db.execute(
        select(Variation).where(Variation.project_id == project.id, Variation.is_deleted.is_(False))
        .order_by(Variation.submitted_date.desc())
    ).scalars().all()
    data = [VariationOut.model_validate(r).model_dump(mode="json") for r in rows]

    def _sum(pred):
        return str(money(sum((D(r["value_try"]) for r in data if pred(r)), D(0))))

    summary = {
        "total_requested": str(money(sum((D(r["value_try"]) for r in data), D(0)))),
        "approved": str(money(sum((D(r["approved_value_try"] or 0) for r in data if r["status"] == "approved"), D(0)))),
        "pending": _sum(lambda r: r["status"] == "pending"),
        "rejected": _sum(lambda r: r["status"] == "rejected"),
        "net_margin_impact": str(money(sum((D(r["margin_impact_try"]) for r in data if r["status"] == "approved"), D(0)))),
    }
    return success(data, meta=summary)


@router.post("/projects/{project_id}/variations")
def create_variation(
    project_id: uuid.UUID, payload: VariationCreate, request: Request,
    user: InvoiceCreatorUser, db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    v = Variation(project_id=project.id, company_id=user.company_id, created_by=user.id, **payload.model_dump())
    db.add(v)
    db.flush()
    if v.status == "approved":
        _sync_category_budget(db, project.id, user.company_id, v.cost_category)
    db.commit()
    db.refresh(v)
    return success(VariationOut.model_validate(v).model_dump(mode="json"))


@router.put("/projects/{project_id}/variations/{variation_id}")
def update_variation(
    project_id: uuid.UUID, variation_id: uuid.UUID, payload: VariationUpdate, request: Request,
    user: InvoiceCreatorUser, db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    v = db.execute(
        select(Variation).where(
            Variation.id == variation_id, Variation.project_id == project.id, Variation.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if v is None:
        raise APIError(404, "NOT_FOUND", "Ek iş bulunamadı")

    changes = payload.model_dump(exclude_unset=True)
    # CR-004-N: approving a variation may require director approval first.
    becoming_approved = changes.get("status") == "approved" and v.status != "approved"
    if becoming_approved:
        from app.models.company import Company
        from app.services import approvals as approvals_service

        company = db.get(Company, user.company_id)
        if approvals_service.is_required(company, "variation_approval"):
            # Apply any non-status edits now; route the approval itself through the workflow.
            non_status = {k: val for k, val in changes.items() if k != "status"}
            old_cat = v.cost_category
            for k, val in non_status.items():
                setattr(v, k, val)
            db.flush()
            approvals_service.create_request(
                db, company_id=user.company_id, project_id=project.id,
                kind="variation_approval", target_table="variations", target_id=v.id,
                payload={
                    "approved_value_try": str(changes.get("approved_value_try")) if changes.get("approved_value_try") is not None else None,
                    "approved_date": changes["approved_date"].isoformat() if changes.get("approved_date") else None,
                },
                description=f"Ek iş onayı — {v.variation_number}: {v.title}",
                amount_try=v.value_try, requested_by=user.id,
            )
            db.commit()
            db.refresh(v)
            out = VariationOut.model_validate(v).model_dump(mode="json")
            out["pending_approval"] = True
            return success(out)

    old_cat = v.cost_category
    for k, val in changes.items():
        setattr(v, k, val)
    db.flush()
    # Recompute affected categories (old + new).
    _sync_category_budget(db, project.id, user.company_id, old_cat)
    if v.cost_category != old_cat:
        _sync_category_budget(db, project.id, user.company_id, v.cost_category)
    db.commit()
    db.refresh(v)
    return success(VariationOut.model_validate(v).model_dump(mode="json"))
