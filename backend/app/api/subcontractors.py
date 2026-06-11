"""Subcontractors router (Section 2.5, 4.5, 3.2)."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.calculations.subcontractor import (
    subcontractor_retention_held,
    subcontractor_revised_contract,
)
from app.db import get_db
from app.deps import CurrentUser, InvoiceCreatorUser
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.responses import APIError, success
from app.schemas.subcontractor import (
    SubcontractorCreate,
    SubcontractorOut,
    SubcontractorUpdate,
)
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["subcontractors"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _sub_totals(db: Session, sub: Subcontractor) -> dict:
    """Compute paid/retention totals from linked cost entries (Section 4.5, 7.1)."""
    entries = db.execute(
        select(CostEntry).where(
            CostEntry.subcontractor_id == sub.id, CostEntry.is_deleted.is_(False)
        )
    ).scalars().all()
    total_paid = money(sum((D(e.amount_paid_try) for e in entries), D(0)))
    total_invoiced = money(sum((D(e.amount_try) for e in entries), D(0)))
    revised = subcontractor_revised_contract(sub.contract_value_try, sub.approved_variations_try)
    retention = subcontractor_retention_held(total_paid, sub.retention_pct)
    out = SubcontractorOut.model_validate(sub).model_dump(mode="json")
    out["revised_contract_try"] = str(revised)
    out["total_paid_try"] = str(total_paid)
    out["total_invoiced_try"] = str(total_invoiced)
    out["retention_held_try"] = str(retention)
    out["progress_pct"] = str(money(D(total_paid) / D(revised) * 100) if revised > 0 else D(0))
    return out


@router.get("/projects/{project_id}/subcontractors")
def list_subs(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    subs = db.execute(
        select(Subcontractor).where(
            Subcontractor.project_id == project.id, Subcontractor.is_deleted.is_(False)
        )
    ).scalars().all()
    data = [_sub_totals(db, s) for s in subs]
    return success(data, meta={"total": len(data)})


@router.post("/projects/{project_id}/subcontractors")
def create_sub(
    project_id: uuid.UUID,
    payload: SubcontractorCreate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    sub = Subcontractor(project_id=project.id, company_id=user.company_id, **payload.model_dump())
    db.add(sub)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="subcontractors",
        record_id=sub.id, action="INSERT", new_values=snapshot(sub), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(sub)
    return success(_sub_totals(db, sub))


@router.put("/projects/{project_id}/subcontractors/{sub_id}")
def update_sub(
    project_id: uuid.UUID,
    sub_id: uuid.UUID,
    payload: SubcontractorUpdate,
    request: Request,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    sub = db.execute(
        select(Subcontractor).where(
            Subcontractor.id == sub_id,
            Subcontractor.project_id == project.id,
            Subcontractor.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if sub is None:
        raise APIError(404, "NOT_FOUND", "Alt yüklenici bulunamadı")

    changes = payload.model_dump(exclude_unset=True)
    real_changes = {k: v for k, v in changes.items() if getattr(sub, k, None) != v}

    # CR-004-N: contract changes may require director approval first.
    from app.models.company import Company
    from app.services import approvals as approvals_service

    company = db.get(Company, user.company_id)
    if real_changes and approvals_service.is_required(company, "subcontractor_change"):
        approvals_service.create_request(
            db, company_id=user.company_id, project_id=project.id,
            kind="subcontractor_change", target_table="subcontractors", target_id=sub.id,
            payload={"changes": {k: (str(v) if hasattr(v, "quantize") else v) for k, v in real_changes.items()}},
            description=f"Alt yüklenici değişikliği — {sub.name}",
            amount_try=real_changes.get("contract_value_try"),
            requested_by=user.id,
        )
        db.commit()
        out = _sub_totals(db, sub)
        out["pending_approval"] = True
        return success(out)

    old = snapshot(sub)
    for k, v in changes.items():
        setattr(sub, k, v)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="subcontractors",
        record_id=sub.id, action="UPDATE", old_values=old, new_values=snapshot(sub),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(sub)
    return success(_sub_totals(db, sub))
