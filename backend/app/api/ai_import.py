"""AI Excel auto-import router (CR-002-H).

POST /projects/{id}/ai-import          -> Claude classifies messy Excel content
POST /projects/{id}/ai-import/confirm  -> save the approved structured records
"""
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.constants import COST_CATEGORY_KEYS
from app.db import get_db
from app.deps import CurrentUser
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog
from app.models.subcontractor import Subcontractor
from app.responses import APIError, success
from app.schemas.cost import CostEntryCreate
from app.schemas.equipment import EquipmentCreate
from app.schemas.invoice import ClientInvoiceCreate
from app.schemas.subcontractor import SubcontractorCreate
from app.services import ai as ai_service
from app.services import fx
from app.services import vendor_backfill
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import invoice_net_due, total_with_vat, vat_amount
from app.services.excel_import import LABEL_TO_KEY, LEGACY_XLS_MESSAGE, excel_to_text, is_legacy_xls

router = APIRouter(tags=["ai-import"])

MAX_BYTES = 10 * 1024 * 1024


class AIImportConfirm(BaseModel):
    maliyet_girisleri: list[dict] = []
    faturalar: list[dict] = []
    alt_yukleniciler: list[dict] = []
    ekipman: list[dict] = []


def _clean(record: dict, drop=("confidence", "raw")) -> dict:
    return {k: v for k, v in record.items() if k not in drop and v is not None}


def _normalise_category(value) -> str | None:
    if not value:
        return None
    if value in COST_CATEGORY_KEYS:
        return value
    return LABEL_TO_KEY.get(str(value).strip().lower())


@router.post("/projects/{project_id}/ai-import")
async def ai_import(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)):
    get_company_project(db, project_id, user)
    # CR-002-I: AI import limited to 5 requests/min/user (Claude cost).
    from app.config import settings
    from app.middleware.limits import enforce_user_limit

    enforce_user_limit(str(user.id), "ai-import", settings.ai_import_rate_per_minute)
    if not ai_service.is_available():
        raise APIError(503, "AI_UNAVAILABLE", "AI şu an kullanılamıyor. Standart içe aktarma kullanın.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Dosya en fazla 10MB olabilir", field="file")
    try:
        text, truncated, rows = excel_to_text(data)
    except Exception as exc:
        if is_legacy_xls(file.filename, exc):
            raise APIError(422, "VALIDATION_ERROR", LEGACY_XLS_MESSAGE, field="file")
        raise APIError(422, "VALIDATION_ERROR", f"Dosya okunamadı: {exc}", field="file")
    # No rows extracted -> say so plainly rather than letting the AI choke on it.
    if rows == 0 or not text.strip():
        raise APIError(422, "VALIDATION_ERROR", "Dosyada veri bulunamadı — sayfa boş olabilir.", field="file")
    try:
        extracted = ai_service.analyze_excel_import(text)
    except ai_service.AIUnavailable:
        # True outage (missing key / transport). The standard import still works.
        raise APIError(503, "AI_UNAVAILABLE", "AI şu an kullanılamıyor. Standart içe aktarma kullanın.")
    except ai_service.AIResponseError as exc:
        # The model answered but the output was unusable — a parse/format problem,
        # NOT an outage. Surface the real reason (CR-015-fix).
        raise APIError(422, "AI_RESPONSE_ERROR", str(exc), field="file")

    analysis = {
        "maliyet_girisleri": len(extracted.get("maliyet_girisleri", [])),
        "faturalar": len(extracted.get("faturalar", [])),
        "alt_yukleniciler": len(extracted.get("alt_yukleniciler", [])),
        "ekipman": len(extracted.get("ekipman", [])),
        "tanimsiz": len(extracted.get("tanimsiz", [])),
        "truncated": truncated,
        "rows_processed": rows,
    }
    return success({"analysis": analysis, "extracted_data": extracted})


@router.post("/projects/{project_id}/ai-import/confirm")
def ai_import_confirm(project_id: uuid.UUID, payload: AIImportConfirm, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    imported = {"maliyet_girisleri": 0, "faturalar": 0, "alt_yukleniciler": 0, "ekipman": 0}
    skipped = 0

    for raw in payload.maliyet_girisleri:
        rec = _clean(raw)
        rec["cost_category"] = _normalise_category(rec.get("cost_category"))
        try:
            item = CostEntryCreate(**rec)
        except ValidationError:
            skipped += 1
            continue
        d = item.model_dump()
        vat = vat_amount(d["amount_try"], d["vat_rate"])
        twv = total_with_vat(d["amount_try"], d["vat_rate"])
        entry = CostEntry(project_id=project.id, company_id=user.company_id, created_by=user.id,
                          vat_amount_try=vat, total_with_vat_try=twv, **d)
        db.add(entry)
        db.flush()
        # CR-008-F: auto-link the AI-imported row to a canonical vendor.
        entry.vendor_id = entry.vendor_id or vendor_backfill.resolve_or_create_vendor_id(
            db, user.company_id, entry.supplier_name
        )
        # CR-014-B parity: snapshot USD so AI-imported rows aren't left amount_usd=NULL.
        fx.snapshot_cost_usd(db, entry)
        record_audit(db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
                     record_id=entry.id, action="INSERT", new_values=snapshot(entry))
        imported["maliyet_girisleri"] += 1

    for raw in payload.faturalar:
        rec = _clean(raw)
        try:
            item = ClientInvoiceCreate(**rec)
        except ValidationError:
            skipped += 1
            continue
        d = item.model_dump()
        inv = ClientInvoice(
            project_id=project.id, company_id=user.company_id, created_by=user.id,
            vat_amount_try=vat_amount(d["amount_try"], d["vat_rate"]),
            total_with_vat_try=total_with_vat(d["amount_try"], d["vat_rate"]),
            net_due_try=invoice_net_due(d["amount_try"], d["vat_rate"], d["retention_amount_try"]),
            amount_received_try=0, payment_status="unpaid", **d,
        )
        db.add(inv)
        try:
            db.flush()
        except Exception:
            db.rollback()
            skipped += 1
            continue
        record_audit(db, company_id=user.company_id, user_id=user.id, table_name="client_invoices",
                     record_id=inv.id, action="INSERT", new_values=snapshot(inv))
        imported["faturalar"] += 1

    for raw in payload.alt_yukleniciler:
        rec = _clean(raw)
        try:
            item = SubcontractorCreate(**rec)
        except ValidationError:
            skipped += 1
            continue
        sub = Subcontractor(project_id=project.id, company_id=user.company_id, **item.model_dump())
        db.add(sub)
        db.flush()
        # CR-008-F: auto-link the AI-imported subcontractor to a canonical vendor.
        sub.vendor_id = sub.vendor_id or vendor_backfill.resolve_or_create_vendor_id(
            db, user.company_id, sub.name
        )
        record_audit(db, company_id=user.company_id, user_id=user.id, table_name="subcontractors",
                     record_id=sub.id, action="INSERT", new_values=snapshot(sub))
        imported["alt_yukleniciler"] += 1

    for raw in payload.ekipman:
        rec = _clean(raw)
        rec.pop("add_to_budget", None)
        try:
            item = EquipmentCreate(**rec)
        except ValidationError:
            skipped += 1
            continue
        e_data = item.model_dump()
        e_data.pop("add_to_budget", None)
        e = EquipmentLog(project_id=project.id, company_id=user.company_id, **e_data)
        db.add(e)
        imported["ekipman"] += 1

    db.commit()
    return success({"imported": imported, "skipped": skipped})
