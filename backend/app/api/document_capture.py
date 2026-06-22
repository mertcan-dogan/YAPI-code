"""Track A — Smart document capture.

Photo or PDF of a supplier invoice → Claude vision extraction → user reviews and
confirms → saved as a cost entry (Gider/Maliyet). The original file is stored in
the PRIVATE `documents` bucket. The AI never writes directly: a human confirms.

POST /projects/{id}/document-capture          -> upload + extract, returns a preview
POST /projects/{id}/document-capture/confirm  -> save the approved cost entry
"""
import hashlib
import uuid
from datetime import date
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import CurrentUser
from app.models.budget_line_item import BudgetLineItem
from app.models.cost_entry import CostEntry
from app.responses import APIError, success
from app.schemas.cost import CostEntryCreate
from app.services import ai as ai_service
from app.services import fx
from app.services import vendor_backfill
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
    # CR-008-F: auto-link the captured cost to a canonical vendor.
    entry.vendor_id = entry.vendor_id or vendor_backfill.resolve_or_create_vendor_id(
        db, user.company_id, entry.supplier_name
    )
    # CR-023.1: snapshot USD like the normal cost-create endpoint, so captured
    # costs don't save with null amount_usd ("kur bulunamadı").
    fx.snapshot_cost_usd(db, entry)
    record_audit(db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
                 record_id=entry.id, action="INSERT", new_values=snapshot(entry))
    db.commit()
    db.refresh(entry)
    return success({"id": str(entry.id), "cost_category": entry.cost_category})


# --- CR-012 Template A — document auto-file (event-driven, on upload) ---------

def _iso_date(v) -> str | None:
    """Best-effort normalise an AI date string to YYYY-MM-DD (or None)."""
    if not v:
        return None
    s = str(v).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    try:
        from datetime import datetime as _dt

        for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return _dt.strptime(s[:10], fmt).date().isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _normalize_autofile_fields(destination: str, raw: dict) -> dict:
    """Shape the AI ``fields`` into the exact keys the approval applier expects
    (same keys the manual confirm endpoints use), so apply stays byte-identical."""
    if destination == "cost":
        return {
            "entry_date": _iso_date(raw.get("invoice_date")),
            "cost_category": raw.get("cost_category") or "material_other",
            "supplier_name": raw.get("supplier_name"),
            "invoice_number": raw.get("invoice_number"),
            "description": raw.get("description"),
            "amount_try": raw.get("amount_try"),
            "vat_rate": raw.get("vat_rate", 20),
            "payment_due_date": _iso_date(raw.get("due_date")),
            "payment_status": "unpaid",
        }
    # client_invoice
    inv_date = _iso_date(raw.get("invoice_date"))
    return {
        "invoice_number": raw.get("invoice_number"),
        "invoice_date": inv_date,
        "due_date": _iso_date(raw.get("due_date")) or inv_date,
        "hakkedis_period": raw.get("hakkedis_period"),
        "description": raw.get("description"),
        "amount_try": raw.get("amount_try"),
        "vat_rate": raw.get("vat_rate", 20),
        "retention_amount_try": raw.get("retention_amount_try", 0),
    }


_DEST_LABELS = {"cost": "Gider", "client_invoice": "Hakediş"}


@router.post("/document-capture/auto-file")
async def auto_file_document(user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)):
    """Auto-file mode: classify the document and, when the automation is enabled and
    the AI is confident enough about an in-subset destination, create a *pending*
    approval proposal (the automation never writes the record — a human approves).
    Otherwise fall back to the manual smart-capture preview (no approval created)."""
    from app.api.automations import TEMPLATE_CATALOG, _get_automation
    from app.middleware.limits import enforce_user_limit
    from app.models.automation import TEMPLATE_DOCUMENT_AUTO_FILE
    from app.services import approvals as approvals_service

    enforce_user_limit(str(user.id), "document-capture", settings.ai_import_rate_per_minute)
    data = await file.read()
    _validate_upload(file, data)
    if not ai_service.is_available():
        raise APIError(503, "AI_UNAVAILABLE", "AI şu an kullanılamıyor. Maliyeti elle girebilirsiniz.")

    auto = _get_automation(db, user.company_id, TEMPLATE_DOCUMENT_AUTO_FILE)
    config = dict(TEMPLATE_CATALOG[TEMPLATE_DOCUMENT_AUTO_FILE]["default_config"])
    if auto and auto.config:
        config.update(auto.config)
    enabled = bool(auto and auto.enabled)

    sha = hashlib.sha256(data).hexdigest()
    ext = ALLOWED[file.content_type]
    path = f"{user.company_id}/inbox/{uuid.uuid4().hex}.{ext}"
    _upload_to_storage(path, data, file.content_type)

    context = _capture_context(db, user)

    # When the automation is off, behave exactly like manual smart capture.
    if not enabled:
        try:
            fields = ai_service.analyze_document_smart(data, file.content_type, context)
        except ai_service.AIUnavailable:
            raise APIError(503, "AI_UNAVAILABLE", "AI belgeyi okuyamadı. Lütfen alanları elle doldurun.")
        checks = _capture_checks(db, user, fields, sha, context)
        return success({
            "mode": "manual", "automation_enabled": False, "extracted": fields,
            "document_path": path, "file_sha256": sha, "projects": context["projects"],
            "duplicates": checks["duplicates"], "anomalies": checks["anomalies"],
        })

    try:
        result = ai_service.analyze_and_classify(data, file.content_type, context)
    except ai_service.AIUnavailable:
        raise APIError(503, "AI_UNAVAILABLE", "AI belgeyi okuyamadı. Lütfen alanları elle doldurun.")

    destination = result.get("destination")
    try:
        confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    min_conf = float(config.get("min_confidence", 0.75))
    allowed = set(config.get("destinations") or []) & {"cost", "client_invoice"}

    # Gate: confident enough AND a routable, in-subset destination -> propose.
    if destination in allowed and confidence >= min_conf:
        fields = _normalize_autofile_fields(destination, result.get("fields") or {})
        # Validate the AI project guess against the company's visible projects.
        guess = result.get("project_guess")
        project_id = None
        proj_ids = {p["id"] for p in context["projects"]}
        if guess and str(guess) in proj_ids:
            project_id = uuid.UUID(str(guess))

        filename = file.filename or "belge"
        desc = f"«{filename}» → {_DEST_LABELS.get(destination, destination)} olarak önerildi"
        amount = None
        try:
            amount = Decimal(str(fields.get("amount_try"))) if fields.get("amount_try") is not None else None
        except Exception:
            amount = None

        req = approvals_service.create_request(
            db, company_id=user.company_id, project_id=project_id,
            kind="agent_file_document", target_table="cost_entries" if destination == "cost" else "client_invoices",
            target_id=None,
            payload={
                "destination": destination,
                "fields": fields,
                "document_path": path,
                "file_sha256": sha,
                "original_filename": filename,
                "confidence": confidence,
                "project_id_guess": str(project_id) if project_id else None,
                "doc_type": result.get("doc_type"),
            },
            description=desc, amount_try=amount, requested_by=user.id, proposed_by_agent=True,
        )
        db.commit()
        return success({
            "mode": "proposed", "automation_enabled": True, "request_id": str(req.id),
            "destination": destination, "confidence": confidence,
            "project_id_guess": str(project_id) if project_id else None,
        })

    # Uncertain or out-of-subset -> fall back to manual preview; create NOTHING.
    try:
        fields = ai_service.analyze_document_smart(data, file.content_type, context)
    except ai_service.AIUnavailable:
        fields = result.get("fields") or {}
    checks = _capture_checks(db, user, fields, sha, context)
    return success({
        "mode": "manual", "automation_enabled": True,
        "fallback_reason": "low_confidence" if confidence < min_conf else "out_of_subset",
        "confidence": confidence, "extracted": fields, "document_path": path, "file_sha256": sha,
        "projects": context["projects"], "duplicates": checks["duplicates"], "anomalies": checks["anomalies"],
    })


# --- Smart capture (company-level): AI suggests project + cost code with reasoning ---

def _capture_context(db: Session, user) -> dict:
    """Build the grounding context for smart capture: active projects with their
    budget categories, cost-category descriptions, and supplier history drawn from
    previously approved cost entries (usual category, projects, typical amount)."""
    from app.api.projects import _list_visible_projects
    from app.constants import COST_CATEGORIES

    projects = _list_visible_projects(db, user, only_active=True)
    proj_ids = [p.id for p in projects]
    pname = {str(p.id): p.name for p in projects}

    cats_by_project: dict = {}
    if proj_ids:
        for pid, cat in db.execute(
            select(BudgetLineItem.project_id, BudgetLineItem.cost_category).where(
                BudgetLineItem.project_id.in_(proj_ids), BudgetLineItem.is_deleted.is_(False)
            )
        ).all():
            cats_by_project.setdefault(pid, set()).add(cat)

    project_list = [
        {"id": str(p.id), "name": p.name, "type": p.project_type, "categories": sorted(cats_by_project.get(p.id, set()))}
        for p in projects
    ]

    # Supplier history from approved (non-pending) cost entries.
    agg: dict = {}
    rows = db.execute(
        select(CostEntry)
        .where(
            CostEntry.company_id == user.company_id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.supplier_name.is_not(None),
        )
        .order_by(CostEntry.entry_date.desc())
        .limit(800)
    ).scalars().all()
    for c in rows:
        name = (c.supplier_name or "").strip()
        if not name:
            continue
        a = agg.setdefault(name, {"cats": {}, "projects": set(), "amounts": []})
        a["cats"][c.cost_category] = a["cats"].get(c.cost_category, 0) + 1
        if str(c.project_id) in pname:
            a["projects"].add(pname[str(c.project_id)])
        a["amounts"].append(float(c.amount_try))
    suppliers = []
    for name, a in sorted(agg.items(), key=lambda kv: -sum(kv[1]["cats"].values()))[:40]:
        amounts = a["amounts"]
        suppliers.append({
            "name": name,
            "usual_category": max(a["cats"], key=a["cats"].get) if a["cats"] else None,
            "projects": sorted(a["projects"]),
            "count": len(amounts),
            "avg_amount": round(sum(amounts) / len(amounts), 2) if amounts else 0,
        })

    return {"projects": project_list, "categories": COST_CATEGORIES, "suppliers": suppliers}


def _try_money(v) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", ".") + " ₺"
    except (TypeError, ValueError):
        return "—"


def _capture_checks(db: Session, user, extracted: dict, file_sha256: str | None, context: dict) -> dict:
    """Phase 2: duplicate + anomaly detection against existing cost entries and
    the supplier/budget history in `context`. Returns warnings only — never blocks."""
    from decimal import Decimal

    from app.constants import COST_CATEGORIES

    supplier = (extracted.get("supplier_name") or "").strip()
    invoice_no = (extracted.get("invoice_number") or "").strip()
    sug_cat = extracted.get("suggested_cost_category")
    sug_proj = extracted.get("suggested_project_id")
    pname = {p["id"]: p["name"] for p in context["projects"]}
    cat_label = lambda k: COST_CATEGORIES.get(k, k)  # noqa: E731

    try:
        amount = Decimal(str(extracted.get("subtotal"))).quantize(Decimal("0.01"))
    except Exception:
        amount = None
    inv_date = None
    try:
        inv_date = date.fromisoformat(str(extracted.get("invoice_date"))[:10])
    except Exception:
        pass

    base = select(CostEntry).where(CostEntry.company_id == user.company_id, CostEntry.is_deleted.is_(False))
    duplicates: list[dict] = []
    by_id: dict = {}

    def add_dup(e, reason: str):
        d = by_id.get(str(e.id))
        if d:
            if reason not in d["reasons"]:
                d["reasons"].append(reason)
            return
        d = {
            "id": str(e.id), "supplier": e.supplier_name, "invoice_number": e.invoice_number,
            "amount_try": str(e.amount_try), "entry_date": e.entry_date.isoformat(),
            "project": pname.get(str(e.project_id)), "reasons": [reason],
        }
        by_id[str(e.id)] = d
        duplicates.append(d)

    if file_sha256:
        for e in db.execute(base.where(CostEntry.document_sha256 == file_sha256)).scalars().all():
            add_dup(e, "Birebir aynı dosya")
    if invoice_no and supplier:
        for e in db.execute(base.where(func.lower(CostEntry.invoice_number) == invoice_no.lower(), func.lower(CostEntry.supplier_name) == supplier.lower())).scalars().all():
            add_dup(e, "Aynı tedarikçi + aynı fatura no")
    if supplier and amount is not None and amount > 0:
        for e in db.execute(base.where(func.lower(CostEntry.supplier_name) == supplier.lower(), CostEntry.amount_try == amount)).scalars().all():
            near = inv_date is None or abs((e.entry_date - inv_date).days) <= 5
            if near:
                add_dup(e, "Aynı tedarikçi + aynı tutar" + (" + yakın tarih" if inv_date else ""))

    # --- Anomalies ---
    anomalies: list[dict] = []
    sup = next((s for s in context["suppliers"] if s["name"].lower() == supplier.lower()), None) if supplier else None
    if sup and amount is not None and sup["avg_amount"] and float(amount) > 3 * sup["avg_amount"]:
        anomalies.append({"type": "amount", "message": f"Tutar ({_try_money(amount)}) bu tedarikçinin ortalamasının ({_try_money(sup['avg_amount'])}) çok üzerinde."})
    if sup and sug_cat and sup["usual_category"] and sug_cat != sup["usual_category"]:
        anomalies.append({"type": "category", "message": f"Bu tedarikçi genellikle '{cat_label(sup['usual_category'])}' kategorisinde; önerilen kategori farklı: '{cat_label(sug_cat)}'."})
    if sup and sug_proj and sup["projects"]:
        sp = pname.get(sug_proj)
        if sp and sp not in sup["projects"]:
            anomalies.append({"type": "project", "message": f"Bu tedarikçi daha önce {', '.join(sup['projects'])} projelerinde kullanılmış; önerilen proje farklı: {sp}."})
    proj = next((p for p in context["projects"] if p["id"] == sug_proj), None) if sug_proj else None
    if proj and sug_cat and proj["categories"] and sug_cat not in proj["categories"]:
        anomalies.append({"type": "budget", "message": f"'{cat_label(sug_cat)}' kategorisi '{proj['name']}' projesinin bütçesinde yer almıyor."})

    return {"duplicates": duplicates, "anomalies": anomalies}


def _validate_upload(file: UploadFile, data: bytes) -> None:
    if file.content_type not in ALLOWED:
        raise APIError(422, "VALIDATION_ERROR", "Sadece JPEG, PNG veya PDF yükleyebilirsiniz", field="file")
    if len(data) > MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Dosya en fazla 10MB olabilir", field="file")
    if not any(data.startswith(sig) for sig in _MAGIC.get(file.content_type, ())):
        raise APIError(422, "VALIDATION_ERROR", "Dosya içeriği belirtilen türle uyuşmuyor", field="file")


@router.post("/document-capture")
async def smart_capture(user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)):
    """Company-level smart capture: extract rich invoice fields and suggest the
    project + cost code (with reasoning), grounded in supplier history and budget."""
    from app.middleware.limits import enforce_user_limit

    enforce_user_limit(str(user.id), "document-capture", settings.ai_import_rate_per_minute)
    data = await file.read()
    _validate_upload(file, data)
    if not ai_service.is_available():
        raise APIError(503, "AI_UNAVAILABLE", "AI şu an kullanılamıyor. Maliyeti elle girebilirsiniz.")

    sha = hashlib.sha256(data).hexdigest()
    ext = ALLOWED[file.content_type]
    path = f"{user.company_id}/inbox/{uuid.uuid4().hex}.{ext}"
    _upload_to_storage(path, data, file.content_type)

    context = _capture_context(db, user)
    try:
        fields = ai_service.analyze_document_smart(data, file.content_type, context)
    except ai_service.AIUnavailable:
        raise APIError(503, "AI_UNAVAILABLE", "AI belgeyi okuyamadı. Lütfen alanları elle doldurun.")

    checks = _capture_checks(db, user, fields, sha, context)
    return success({
        "extracted": fields,
        "document_path": path,
        "file_sha256": sha,
        "projects": context["projects"],
        "duplicates": checks["duplicates"],
        "anomalies": checks["anomalies"],
    })


class SmartCaptureConfirm(BaseModel):
    project_id: uuid.UUID
    document_path: str | None = None
    file_sha256: str | None = None
    entry_date: date
    cost_category: str
    supplier_name: str | None = None
    invoice_number: str | None = None
    description: str | None = None
    amount_try: Decimal
    vat_rate: Decimal = Decimal("20")
    payment_due_date: date | None = None
    payment_status: str = "unpaid"


@router.post("/document-capture/confirm")
def smart_capture_confirm(payload: SmartCaptureConfirm, user: CurrentUser, db: Session = Depends(get_db)):
    """Save the reviewed cost to the chosen project, storing the document + its hash."""
    project = get_company_project(db, payload.project_id, user)
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
        vat_amount_try=vat, total_with_vat_try=twv, document_sha256=payload.file_sha256, **d,
    )
    db.add(entry)
    db.flush()
    # CR-008-F: auto-link the captured cost to a canonical vendor.
    entry.vendor_id = entry.vendor_id or vendor_backfill.resolve_or_create_vendor_id(
        db, user.company_id, entry.supplier_name
    )
    # CR-023.1: snapshot USD like the normal cost-create endpoint, so smart-capture
    # costs don't save with null amount_usd ("kur bulunamadı").
    fx.snapshot_cost_usd(db, entry)
    record_audit(db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
                 record_id=entry.id, action="INSERT", new_values=snapshot(entry))
    db.commit()
    db.refresh(entry)
    return success({"id": str(entry.id), "cost_category": entry.cost_category})
