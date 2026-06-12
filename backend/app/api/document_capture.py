"""Track A — Smart document capture.

Photo or PDF of a supplier invoice → Claude vision extraction → user reviews and
confirms → saved as a cost entry (Gider/Maliyet). The original file is stored in
the PRIVATE `documents` bucket. The AI never writes directly: a human confirms.

POST /projects/{id}/document-capture          -> upload + extract, returns a preview
POST /projects/{id}/document-capture/confirm  -> save the approved cost entry
"""
import uuid
from datetime import date
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import CurrentUser
from app.models.cost_entry import CostEntry
from app.responses import APIError, success
from app.schemas.cost import CostEntryCreate
from app.services import ai as ai_service
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import total_with_vat, vat_amount

router = APIRouter(tags=["document-capture"])

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
_MAGIC = {
    "application/pdf": (b"%PDF",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}
DOCS_BUCKET = "documents"


def _upload_to_storage(path: str, data: bytes, content_type: str) -> None:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Dosya depolama yapılandırılmadı")
    url = f"{settings.supabase_url}/storage/v1/object/{DOCS_BUCKET}/{path}"
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "Belge yüklenemedi")
    if resp.status_code not in (200, 201):
        raise APIError(502, "STORAGE_ERROR", f"Belge yüklenemedi (depolama hatası {resp.status_code})")


@router.post("/projects/{project_id}/document-capture")
async def capture_document(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    """Upload a photo/PDF and return AI-extracted fields for review (no save)."""
    get_company_project(db, project_id, user)
    from app.middleware.limits import enforce_user_limit

    enforce_user_limit(str(user.id), "document-capture", settings.ai_import_rate_per_minute)
    if file.content_type not in ALLOWED:
        raise APIError(422, "VALIDATION_ERROR", "Sadece JPEG, PNG veya PDF yükleyebilirsiniz", field="file")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Dosya en fazla 10MB olabilir", field="file")
    if not any(data.startswith(sig) for sig in _MAGIC.get(file.content_type, ())):
        raise APIError(422, "VALIDATION_ERROR", "Dosya içeriği belirtilen türle uyuşmuyor", field="file")
    if not ai_service.is_available():
        raise APIError(503, "AI_UNAVAILABLE", "AI şu an kullanılamıyor. Maliyeti elle girebilirsiniz.")

    ext = ALLOWED[file.content_type]
    path = f"{user.company_id}/{project_id}/{uuid.uuid4().hex}.{ext}"
    _upload_to_storage(path, data, file.content_type)

    try:
        fields = ai_service.analyze_document_image(data, file.content_type)
    except ai_service.AIUnavailable:
        raise APIError(503, "AI_UNAVAILABLE", "AI belgeyi okuyamadı. Lütfen alanları elle doldurun.")

    return success({"extracted": fields, "document_path": path})


class CaptureConfirm(BaseModel):
    document_path: str | None = None
    entry_date: date
    cost_category: str
    supplier_name: str | None = None
    invoice_number: str | None = None
    description: str | None = None
    amount_try: Decimal
    vat_rate: Decimal = Decimal("20")
    payment_due_date: date | None = None
    payment_status: str = "unpaid"


@router.post("/projects/{project_id}/document-capture/confirm")
def confirm_document(
    project_id: uuid.UUID,
    payload: CaptureConfirm,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """Save the user-reviewed fields as a cost entry, linking the stored document."""
    project = get_company_project(db, project_id, user)
    doc_url = f"{DOCS_BUCKET}/{payload.document_path}" if payload.document_path else None
    try:
        rec = CostEntryCreate(
            entry_date=payload.entry_date,
            cost_category=payload.cost_category,
            supplier_name=payload.supplier_name,
            invoice_number=payload.invoice_number,
            description=payload.description,
            amount_try=payload.amount_try,
            vat_rate=payload.vat_rate,
            payment_due_date=payload.payment_due_date,
            payment_status=payload.payment_status,
            document_url=doc_url,
        )
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "Geçersiz veri") if exc.errors() else "Geçersiz veri"
        raise APIError(422, "VALIDATION_ERROR", str(msg))

    d = rec.model_dump()
    vat = vat_amount(d["amount_try"], d["vat_rate"])
    twv = total_with_vat(d["amount_try"], d["vat_rate"])
    entry = CostEntry(
        project_id=project.id, company_id=user.company_id, created_by=user.id,
        vat_amount_try=vat, total_with_vat_try=twv, **d,
    )
    db.add(entry)
    db.flush()
    record_audit(db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
                 record_id=entry.id, action="INSERT", new_values=snapshot(entry))
    db.commit()
    db.refresh(entry)
    return success({"id": str(entry.id), "cost_category": entry.cost_category})
