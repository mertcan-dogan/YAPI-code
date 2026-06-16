"""Equipment log router (Section 2.5, 4.8)."""
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.equipment import equipment_cost, equipment_duration_days
from app.calculations.money import D, money, safe_div
from app.config import settings as app_settings
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

logger = logging.getLogger(__name__)

# Equipment photos: upload — mirrors the company-logo path (api/settings.py):
# Supabase Storage public bucket + magic-byte validation.
PHOTO_BUCKET = "equipment-photos"
PHOTO_MAX_BYTES = 5 * 1024 * 1024  # ~5MB
PHOTO_ALLOWED = {"image/png": "png", "image/jpeg": "jpg"}
_PHOTO_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_equipment(db: Session, project_id, equipment_id) -> EquipmentLog:
    e = db.execute(
        select(EquipmentLog).where(
            EquipmentLog.id == equipment_id,
            EquipmentLog.project_id == project_id,
            EquipmentLog.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if e is None:
        raise APIError(404, "NOT_FOUND", "Ekipman bulunamadı")
    return e


def _equipment_description(e: EquipmentLog) -> str:
    end = e.deployment_end.isoformat() if e.deployment_end else "—"
    return f"{e.equipment_name} — {e.deployment_start.isoformat()} - {end} — otomatik oluşturuldu"


def _create_budget_entry_for_equipment(db, user, project_id, e: EquipmentLog) -> None:
    """CR-001-E/CR-002-E: auto-create a committed cost_entry mirroring equipment cost.

    amount_try = equipment_cost; vat 20%; total_with_vat = amount × 1.20.
    """
    amount = equipment_cost(
        e.ownership_type, e.rate_try, e.rate_unit, e.deployment_start, e.deployment_end,
        e.fuel_maintenance_try,
    )
    if amount <= 0:
        return
    category = "equipment_rented" if e.ownership_type == "rented" else "equipment_owned"
    vat_rate = D(20)
    vat = money(amount * vat_rate / D(100))
    entry = CostEntry(
        project_id=project_id,
        company_id=user.company_id,
        created_by=user.id,
        entry_date=e.deployment_start,
        cost_category=category,
        supplier_name=e.supplier_name,
        description=_equipment_description(e),
        amount_try=amount,
        vat_rate=vat_rate,
        vat_amount_try=vat,
        total_with_vat_try=money(amount + vat),
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


# --------------------------------------------------------------------------- #
# Equipment photos (Supabase Storage public bucket)
# --------------------------------------------------------------------------- #
class PhotoDelete(BaseModel):
    url: str


@router.post("/projects/{project_id}/equipment/{equipment_id}/photos")
async def upload_equipment_photo(
    project_id: uuid.UUID,
    equipment_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Ekipman fotoğrafı yükle (PNG/JPEG, max ~5MB) ve photo_urls'e ekle."""
    project = get_company_project(db, project_id, user)
    e = _get_equipment(db, project.id, equipment_id)

    if file.content_type not in PHOTO_ALLOWED:
        raise APIError(422, "VALIDATION_ERROR",
                       "Sadece PNG veya JPEG yükleyebilirsiniz", field="file")
    data = await file.read()
    if len(data) > PHOTO_MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Fotoğraf en fazla 5MB olabilir", field="file")
    if not any(data.startswith(sig) for sig in _PHOTO_MAGIC.get(file.content_type, ())):
        raise APIError(422, "VALIDATION_ERROR",
                       "Dosya içeriği belirtilen türle uyuşmuyor", field="file")

    if not app_settings.supabase_url or not app_settings.supabase_service_key:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Dosya depolama yapılandırılmadı")

    ext = PHOTO_ALLOWED[file.content_type]
    object_path = f"equipment_photos/{user.company_id}/{equipment_id}/{uuid.uuid4().hex}.{ext}"
    url = f"{app_settings.supabase_url}/storage/v1/object/{PHOTO_BUCKET}/{object_path}"
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {app_settings.supabase_service_key}",
                "Content-Type": file.content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "Fotoğraf yüklenemedi")
    if resp.status_code not in (200, 201):
        logger.error("Equipment photo upload failed: storage %s %s", resp.status_code, resp.text[:300])
        raise APIError(502, "STORAGE_ERROR", f"Fotoğraf yüklenemedi (depolama hatası {resp.status_code})")

    public_url = (
        f"{app_settings.supabase_url}/storage/v1/object/public/{PHOTO_BUCKET}/{object_path}"
    )
    old = list(e.photo_urls or [])
    e.photo_urls = [*old, public_url]
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="equipment_log",
        record_id=e.id, action="UPDATE",
        old_values={"photo_urls": old}, new_values={"photo_urls": e.photo_urls},
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(e)
    return success(_serialize(e))


@router.delete("/projects/{project_id}/equipment/{equipment_id}/photos")
def delete_equipment_photo(
    project_id: uuid.UUID,
    equipment_id: uuid.UUID,
    payload: PhotoDelete,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Bir ekipman fotoğrafını kaldır — photo_urls'ten çıkar, depolamadan sil."""
    project = get_company_project(db, project_id, user)
    e = _get_equipment(db, project.id, equipment_id)

    old = list(e.photo_urls or [])
    if payload.url not in old:
        raise APIError(404, "NOT_FOUND", "Fotoğraf bulunamadı")

    # Best-effort storage cleanup; never fail the request if it errors.
    marker = f"/storage/v1/object/public/{PHOTO_BUCKET}/"
    if marker in payload.url and app_settings.supabase_url and app_settings.supabase_service_key:
        object_path = payload.url.split(marker, 1)[1]
        try:
            httpx.request(
                "DELETE",
                f"{app_settings.supabase_url}/storage/v1/object/{PHOTO_BUCKET}/{object_path}",
                headers={"Authorization": f"Bearer {app_settings.supabase_service_key}"},
                timeout=15,
            )
        except httpx.HTTPError:
            pass

    e.photo_urls = [u for u in old if u != payload.url]
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="equipment_log",
        record_id=e.id, action="UPDATE",
        old_values={"photo_urls": old}, new_values={"photo_urls": e.photo_urls},
        ip_address=_ip(request),
    )
    db.commit()
    db.refresh(e)
    return success(_serialize(e))
