"""Excel import router (Section 9.1)."""
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.cost_entry import CostEntry
from app.responses import APIError, success
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import total_with_vat, vat_amount
from app.services.excel_import import build_template, validate_rows

router = APIRouter(tags=["imports"])


@router.get("/projects/{project_id}/import/template")
def download_template(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    get_company_project(db, project_id, user)
    data = build_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="yapi-maliyet-sablonu.xlsx"'},
    )


@router.post("/projects/{project_id}/import/preview")
async def preview_import(
    project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)
):
    get_company_project(db, project_id, user)
    data = await file.read()
    try:
        rows = validate_rows(data)
    except Exception as exc:
        raise APIError(422, "VALIDATION_ERROR", f"Dosya okunamadı: {exc}", field="file")
    valid = sum(1 for r in rows if r["valid"])
    # Serialise Decimals/dates for transport.
    out = []
    for r in rows:
        d = {k: (str(v) if hasattr(v, "isoformat") or hasattr(v, "quantize") else v) for k, v in r["data"].items()}
        out.append({"row": r["row"], "valid": r["valid"], "errors": r["errors"], "data": d})
    return success(out, meta={"total": len(rows), "valid": valid, "invalid": len(rows) - valid})


@router.post("/projects/{project_id}/import/confirm")
async def confirm_import(
    project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)
):
    project = get_company_project(db, project_id, user)
    data = await file.read()
    rows = validate_rows(data)
    imported = 0
    skipped = 0
    for r in rows:
        if not r["valid"]:
            skipped += 1
            continue
        d = r["data"]
        vat = vat_amount(d["amount_try"], d["vat_rate"])
        twv = total_with_vat(d["amount_try"], d["vat_rate"])
        entry = CostEntry(
            project_id=project.id, company_id=user.company_id, created_by=user.id,
            entry_type="actual", vat_amount_try=vat, total_with_vat_try=twv,
            amount_paid_try=twv if d["payment_status"] == "paid" else 0, **d,
        )
        db.add(entry)
        db.flush()
        record_audit(
            db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
            record_id=entry.id, action="INSERT", new_values=snapshot(entry),
        )
        imported += 1
    db.commit()
    return success({"imported": imported, "skipped": skipped})
