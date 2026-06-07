"""Equipment log router (Section 2.5, 4.8)."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.equipment import equipment_cost, equipment_duration_days
from app.calculations.money import D, money, safe_div
from app.db import get_db
from app.deps import CurrentUser
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog
from app.responses import APIError, success
from app.schemas.equipment import EquipmentCreate, EquipmentOut, EquipmentUpdate
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.financials import project_financials

router = APIRouter(tags=["equipment"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _create_budget_entry_for_equipment(db, user, project_id, e: EquipmentLog) -> None:
    """CR-001-E: auto-create a committed cost_entry mirroring the equipment cost."""
    amount = equipment_cost(
        e.ownership_type, e.rate_try, e.rate_unit, e.deployment_start, e.deployment_end,
        e.fuel_maintenance_try,
    )
    if amount <= 0:
        return
    category = "equipment_rented" if e.ownership_type == "rented" else "equipment_owned"
    entry = CostEntry(
        project_id=project_id,
        company_id=user.company_id,
        created_by=user.id,
        entry_date=e.deployment_start,
        cost_category=category,
        supplier_name=e.supplier_name,
        description=f"{e.equipment_name} — otomatik oluşturuldu",
        amount_try=amount,
        vat_rate=D(0),
        vat_amount_try=D(0),
        total_with_vat_try=amount,
        entry_type="committed",
    )
    db.add(entry)
    db.flush()
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
        record_id=entry.id, action="INSERT", new_values=snapshot(entry),
    )


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
    data = payload.model_dump()
    add_to_budget = data.pop("add_to_budget", True)
    e = EquipmentLog(project_id=project.id, company_id=user.company_id, **data)
    db.add(e)
    db.flush()
    if add_to_budget:
        _create_budget_entry_for_equipment(db, user, project.id, e)
    db.commit()
    db.refresh(e)
    return success(_serialize(e))


@router.put("/projects/{project_id}/equipment/{equipment_id}")
def update_equipment(
    project_id: uuid.UUID,
    equipment_id: uuid.UUID,
    payload: EquipmentUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """CR-001-G: edit an equipment record."""
    project = get_company_project(db, project_id, user)
    e = db.execute(
        select(EquipmentLog).where(
            EquipmentLog.id == equipment_id,
            EquipmentLog.project_id == project.id,
            EquipmentLog.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if e is None:
        raise APIError(404, "NOT_FOUND", "Ekipman bulunamadı")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return success(_serialize(e))
