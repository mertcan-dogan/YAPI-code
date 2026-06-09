"""Approval workflow router (CR-003-J). Director only."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import DirectorUser
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.responses import APIError, success
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["approvals"])


class RejectBody(BaseModel):
    reason: str


@router.get("/approvals")
def list_approvals(user: DirectorUser, db: Session = Depends(get_db)):
    """Pending items awaiting the director's decision (company-wide)."""
    project_names = {
        p.id: p.name
        for p in db.execute(
            select(Project).where(Project.company_id == user.company_id, Project.is_deleted.is_(False))
        ).scalars().all()
    }
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.company_id == user.company_id,
            CostEntry.pending_approval.is_(True),
            CostEntry.is_deleted.is_(False),
        ).order_by(CostEntry.created_at.desc())
    ).scalars().all()
    items = [
        {
            "kind": "cost_entry",
            "id": str(c.id),
            "project_id": str(c.project_id),
            "project_name": project_names.get(c.project_id, ""),
            "description": c.description or c.cost_category,
            "amount_try": str(c.total_with_vat_try),
            "created_by": str(c.created_by),
            "created_at": c.created_at.isoformat(),
        }
        for c in costs
    ]
    return success(items, meta={"total": len(items)})


def _get_pending_cost(db: Session, user, cost_id: uuid.UUID) -> CostEntry:
    cost = db.execute(
        select(CostEntry).where(
            CostEntry.id == cost_id,
            CostEntry.company_id == user.company_id,
            CostEntry.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if cost is None or not cost.pending_approval:
        raise APIError(404, "NOT_FOUND", "Onay bekleyen kayıt bulunamadı")
    return cost


@router.put("/approvals/cost/{cost_id}/approve")
def approve_cost(cost_id: uuid.UUID, request: Request, user: DirectorUser, db: Session = Depends(get_db)):
    cost = _get_pending_cost(db, user, cost_id)
    old = snapshot(cost)
    cost.pending_approval = False
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="UPDATE", old_values=old, new_values=snapshot(cost),
    )
    db.commit()
    return success({"id": str(cost_id), "message": "Onaylandı"})


@router.put("/approvals/cost/{cost_id}/reject")
def reject_cost(cost_id: uuid.UUID, payload: RejectBody, request: Request, user: DirectorUser, db: Session = Depends(get_db)):
    if not payload.reason.strip():
        raise APIError(422, "VALIDATION_ERROR", "Red nedeni zorunludur", field="reason")
    cost = _get_pending_cost(db, user, cost_id)
    old = snapshot(cost)
    cost.is_deleted = True
    cost.deleted_at = datetime.now(timezone.utc)
    cost.approval_reason = payload.reason.strip()
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=cost.id, action="DELETE", old_values=old, new_values=snapshot(cost),
    )
    db.commit()
    return success({"id": str(cost_id), "message": "Reddedildi"})
