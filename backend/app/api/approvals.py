"""Approval workflow router (CR-003-J). Director only."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import DirectorUser
from app.models.approval_request import ApprovalRequest
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.responses import APIError, success
from app.services import approvals as approvals_service
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["approvals"])

# Turkish labels for the generic request kinds.
KIND_LABELS = {
    "cost_entry": "Maliyet Girişi",
    "budget_change": "Bütçe Değişikliği",
    "subcontractor_change": "Alt Yüklenici Değişikliği",
    "cost_deletion": "Maliyet Silme",
    "variation_approval": "Ek İş Onayı",
    # CR-011-C — agent-proposed action kinds.
    "agent_reminder": "Hatırlatıcı (AI önerisi)",
    "agent_flag_invoice": "İnceleme İşareti (AI önerisi)",
    "agent_task": "Görev (AI önerisi)",
    # CR-012 Template A — document auto-file proposal.
    "agent_file_document": "Belge Dosyalama (AI önerisi)",
}


class RejectBody(BaseModel):
    reason: str


class ApproveBody(BaseModel):
    """Optional patch sent on approve. For ``agent_file_document`` the approver can
    correct the extracted fields and (when the AI guess was null) pick the project
    before the record is created."""
    project_id: uuid.UUID | None = None
    fields: dict | None = None


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
            "kind_label": KIND_LABELS["cost_entry"],
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

    # CR-004-N: generic approval requests (budget / subcontractor / deletion / variation).
    requests = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.company_id == user.company_id,
            ApprovalRequest.status == "pending",
            ApprovalRequest.is_deleted.is_(False),
        ).order_by(ApprovalRequest.created_at.desc())
    ).scalars().all()
    for r in requests:
        item = {
            "kind": r.kind,
            "kind_label": KIND_LABELS.get(r.kind, r.kind),
            "id": str(r.id),
            "request_id": str(r.id),
            "project_id": str(r.project_id) if r.project_id else None,
            "project_name": project_names.get(r.project_id, "") if r.project_id else "",
            "description": r.description or "",
            "amount_try": str(r.amount_try) if r.amount_try is not None else None,
            "created_by": str(r.requested_by),
            "created_at": r.created_at.isoformat(),
            # CR-011-C — lets the UI badge agent-proposed requests ("Yapı AI öneriyor").
            "proposed_by_agent": bool(r.proposed_by_agent),
        }
        # CR-012: the auto-file card needs the destination, editable fields and
        # the CR-024 confidence to render (the doc bytes stay in the bucket).
        if r.kind == "agent_file_document":
            item["payload"] = r.payload
        items.append(item)
    return success(items, meta={"total": len(items)})


def _get_pending_request(db: Session, user, req_id: uuid.UUID) -> ApprovalRequest:
    req = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == req_id,
            ApprovalRequest.company_id == user.company_id,
            ApprovalRequest.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if req is None or req.status != "pending":
        raise APIError(404, "NOT_FOUND", "Onay bekleyen kayıt bulunamadı")
    return req


@router.put("/approvals/request/{req_id}/approve")
def approve_request(
    req_id: uuid.UUID,
    user: DirectorUser,
    db: Session = Depends(get_db),
    payload: ApproveBody | None = Body(default=None),
):
    req = _get_pending_request(db, user, req_id)
    # CR-012: apply the approver's corrections (edited fields + chosen project)
    # to an auto-file proposal before the record is created.
    if payload and req.kind == "agent_file_document":
        patched = dict(req.payload or {})
        if payload.fields:
            patched["fields"] = {**(patched.get("fields") or {}), **payload.fields}
        req.payload = patched
        if payload.project_id is not None:
            from app.services.access import get_company_project

            get_company_project(db, payload.project_id, user)  # 404s if not in company
            req.project_id = payload.project_id
    approvals_service.apply_request(db, req)
    approvals_service.mark_decided(req, user_id=user.id, status="approved")
    db.commit()
    return success({"id": str(req_id), "message": "Onaylandı"})


@router.put("/approvals/request/{req_id}/reject")
def reject_request(req_id: uuid.UUID, payload: RejectBody, user: DirectorUser, db: Session = Depends(get_db)):
    if not payload.reason.strip():
        raise APIError(422, "VALIDATION_ERROR", "Red nedeni zorunludur", field="reason")
    req = _get_pending_request(db, user, req_id)
    approvals_service.mark_decided(req, user_id=user.id, status="rejected", reason=payload.reason.strip())
    db.commit()
    return success({"id": str(req_id), "message": "Reddedildi"})


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
