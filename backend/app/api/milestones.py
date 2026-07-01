"""Project milestones router (CR-019-A) — the SCHEDULE lane.

Company-scoped CRUD over ``project_milestones`` + a weighted schedule rollup
(overall + per-stage), computed in SQL. Directors and project managers may edit
(day-to-day operational data, §1.2). Milestones drive progress/deadline signals
ONLY — they must never feed billing/margin/forecast money figures (§0.2).
"""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MILESTONE_STATUS_DONE
from app.db import get_db
from app.deps import CurrentUser, DirectorOrPMUser
from app.models.project_milestone import ProjectMilestone
from app.responses import APIError, success
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneOut,
    MilestoneReorder,
    MilestoneUpdate,
)
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.milestones import compute_schedule_rollup

router = APIRouter(tags=["milestones"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _serialize(m: ProjectMilestone) -> dict:
    return MilestoneOut.model_validate(m).model_dump(mode="json")


def _get_milestone(db: Session, project, milestone_id: uuid.UUID) -> ProjectMilestone:
    m = db.execute(
        select(ProjectMilestone).where(
            ProjectMilestone.id == milestone_id,
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.company_id == project.company_id,
            ProjectMilestone.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if m is None:
        raise APIError(404, "NOT_FOUND", "Kilometre taşı bulunamadı")
    return m


@router.get("/projects/{project_id}/milestones")
def list_milestones(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = db.execute(
        select(ProjectMilestone)
        .where(
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.company_id == project.company_id,
            ProjectMilestone.is_deleted.is_(False),
        )
        .order_by(ProjectMilestone.sort_order, ProjectMilestone.created_at)
    ).scalars().all()
    rollup = compute_schedule_rollup(db, project.id, project.company_id)
    return success([_serialize(m) for m in rows], meta=rollup)


@router.post("/projects/{project_id}/milestones")
def create_milestone(
    project_id: uuid.UUID,
    payload: MilestoneCreate,
    request: Request,
    user: DirectorOrPMUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    data = payload.model_dump()
    # Mark-complete convenience: completing without an explicit date stamps today.
    if data.get("status") == MILESTONE_STATUS_DONE and data.get("completed_date") is None:
        data["completed_date"] = date.today()
    m = ProjectMilestone(project_id=project.id, company_id=project.company_id, **data)
    db.add(m)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="project_milestones",
        record_id=m.id, action="INSERT", new_values=snapshot(m), ip_address=_ip(request),
    )
    db.commit()
    db.refresh(m)
    return success(_serialize(m))


@router.put("/projects/{project_id}/milestones/reorder")
def reorder_milestones(
    project_id: uuid.UUID,
    payload: MilestoneReorder,
    request: Request,
    user: DirectorOrPMUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    for item in payload.items:
        m = _get_milestone(db, project, item.id)
        m.sort_order = item.sort_order
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="project_milestones",
        record_id=project.id, action="UPDATE",
        new_values={"reorder": [{"id": str(i.id), "sort_order": i.sort_order} for i in payload.items]},
        ip_address=_ip(request),
    )
    db.commit()
    rows = db.execute(
        select(ProjectMilestone)
        .where(
            ProjectMilestone.project_id == project.id,
            ProjectMilestone.is_deleted.is_(False),
        )
        .order_by(ProjectMilestone.sort_order, ProjectMilestone.created_at)
    ).scalars().all()
    return success([_serialize(m) for m in rows])


@router.put("/projects/{project_id}/milestones/{milestone_id}")
def update_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    payload: MilestoneUpdate,
    request: Request,
    user: DirectorOrPMUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    m = _get_milestone(db, project, milestone_id)
    changes = payload.model_dump(exclude_unset=True)

    # Mark-complete: moving to done stamps completed_date (today) unless supplied.
    if changes.get("status") == MILESTONE_STATUS_DONE and "completed_date" not in changes and m.completed_date is None:
        changes["completed_date"] = date.today()

    old = snapshot(m)
    for k, v in changes.items():
        setattr(m, k, v)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="project_milestones",
        record_id=m.id, action="UPDATE", old_values=old, new_values=snapshot(m),
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(m)
    return success(_serialize(m))


@router.delete("/projects/{project_id}/milestones/{milestone_id}")
def delete_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    request: Request,
    user: DirectorOrPMUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    m = _get_milestone(db, project, milestone_id)
    old = snapshot(m)
    m.is_deleted = True
    m.deleted_at = datetime.now(timezone.utc)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="project_milestones",
        record_id=m.id, action="DELETE", old_values=old, ip_address=_ip(request),
    )
    db.commit()
    return success({"id": str(milestone_id), "deleted": True})
