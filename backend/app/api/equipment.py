"""Equipment log router (Section 2.5, 4.8)."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.equipment import equipment_cost, equipment_duration_days
from app.calculations.money import D, money, safe_div
from app.db import get_db
from app.deps import CurrentUser
from app.models.equipment_log import EquipmentLog
from app.responses import success
from app.schemas.equipment import EquipmentCreate, EquipmentOut
from app.services.access import get_company_project
from app.services.financials import project_financials

router = APIRouter(tags=["equipment"])


def _serialize(e: EquipmentLog) -> dict:
    out = EquipmentOut.model_validate(e).model_dump(mode="json")
    out["duration_days"] = equipment_duration_days(e.deployment_start, e.deployment_end)
    out["total_cost_try"] = str(
        equipment_cost(e.ownership_type, e.rate_try, e.rate_unit, e.deployment_start,
                       e.deployment_end, e.fuel_maintenance_try)
    )
    return out


@router.get("/projects/{project_id}/equipment")
def list_equipment(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = db.execute(
        select(EquipmentLog).where(
            EquipmentLog.project_id == project.id, EquipmentLog.is_deleted.is_(False)
        )
    ).scalars().all()
    data = [_serialize(e) for e in rows]
    total_cost = money(sum((D(r["total_cost_try"]) for r in data), D(0)))
    f = project_financials(db, project)
    pct_of_budget = money(safe_div(total_cost, f["revised_budget_try"]) * 100)
    return success(
        data,
        meta={"total": len(data), "total_cost_try": str(total_cost), "pct_of_budget": str(pct_of_budget)},
    )


@router.post("/projects/{project_id}/equipment")
def add_equipment(
    project_id: uuid.UUID,
    payload: EquipmentCreate,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    e = EquipmentLog(project_id=project.id, company_id=user.company_id, **payload.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    return success(_serialize(e))
