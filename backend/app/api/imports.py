"""Excel import router (Section 9.1 + CR-001-F).

Flow:
  GET  /projects/{id}/costs/import/template  -> download .xlsx template
  POST /projects/{id}/costs/import/preview   -> parse+validate a file, NO save
  POST /projects/{id}/costs/import/confirm   -> bulk-save edited rows (all-or-nothing)
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.cost_entry import CostEntry
from app.responses import APIError, success
from app.schemas.cost import CostEntryCreate
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot
from app.services.calc_fields import total_with_vat, vat_amount
from app.services.excel_import import LEGACY_XLS_MESSAGE, build_template, is_legacy_xls, list_sheet_names, validate_rows

router = APIRouter(tags=["imports"])


class ImportConfirmRequest(BaseModel):
    rows: list[dict]


def _serialize_row(r: dict) -> dict:
    data = {
        k: (str(v) if hasattr(v, "isoformat") or hasattr(v, "quantize") else v)
        for k, v in r["data"].items()
    }
    return {"row": r["row"], "valid": r["valid"], "skipped": r.get("skipped", False),
            "errors": r["errors"], "data": data}


@router.get("/projects/{project_id}/costs/import/template")
def download_template(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    get_company_project(db, project_id, user)
    data = build_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="yapi-maliyet-sablonu.xlsx"'},
    )


@router.post("/projects/{project_id}/costs/import/sheets")
async def import_sheets(
    project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db), file: UploadFile = File(...)
):
    """CR-002-F: list the sheet names in an uploaded workbook (for the picker)."""
    get_company_project(db, project_id, user)
    data = await file.read()
    try:
        sheets = list_sheet_names(data)
    except Exception as exc:
        if is_legacy_xls(file.filename, exc):
            raise APIError(422, "VALIDATION_ERROR", LEGACY_XLS_MESSAGE, field="file")
        raise APIError(422, "VALIDATION_ERROR", f"Dosya okunamadı: {exc}", field="file")
    return success({"sheets": sheets})


@router.post("/projects/{project_id}/costs/import/preview")
async def preview_import(
    project_id: uuid.UUID,
    user: CurrentUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
):
    get_company_project(db, project_id, user)
    # CR-002-I: Excel import limited to 10 requests/min/user.
    from app.config import settings
    from app.middleware.limits import enforce_user_limit

    enforce_user_limit(str(user.id), "import", settings.import_rate_per_minute)
    data = await file.read()
    try:
        result = validate_rows(data, sheet_name=sheet_name)
    except Exception as exc:
        if is_legacy_xls(file.filename, exc):
            raise APIError(422, "VALIDATION_ERROR", LEGACY_XLS_MESSAGE, field="file")
        raise APIError(422, "VALIDATION_ERROR", f"Dosya okunamadı: {exc}", field="file")
    rows = result["rows"]
    valid = sum(1 for r in rows if r["valid"])
    skipped = sum(1 for r in rows if r.get("skipped"))
    invalid = sum(1 for r in rows if not r["valid"] and not r.get("skipped"))
    out = [_serialize_row(r) for r in rows]
    return success(
        out,
        meta={
            "total": len(rows),
            "valid": valid,
            "invalid": invalid,
            "skipped": skipped,
            "header_detected": result["header_detected"],
            "header_row": result["header_row"],
            # CR-015-fix: column mapping + an honest reason when nothing imports.
            "column_map": result.get("column_map", {}),
            "message": result.get("message"),
        },
    )


@router.post("/projects/{project_id}/costs/import/confirm")
def confirm_import(
    project_id: uuid.UUID,
    payload: ImportConfirmRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    """All-or-nothing bulk save of (possibly edited) rows. Validates every row
    server-side; if ANY row is invalid nothing is saved (CR-001-F)."""
    project = get_company_project(db, project_id, user)
    if not payload.rows:
        raise APIError(422, "VALIDATION_ERROR", "İçe aktarılacak satır yok")

    validated: list[CostEntryCreate] = []
    errors: list[dict] = []
    for idx, raw in enumerate(payload.rows):
        try:
            validated.append(CostEntryCreate(**raw))
        except ValidationError as exc:
            first = exc.errors()[0]
            msg = first.get("msg", "Geçersiz satır").replace("Value error, ", "")
            errors.append({"row": idx + 1, "field": (first.get("loc") or [None])[-1], "message": msg})

    if errors:
        # Reject the whole batch — partial import is not allowed.
        raise APIError(422, "VALIDATION_ERROR", f"{len(errors)} satır geçersiz. İçe aktarma iptal edildi.")

    # Single transaction: either all rows persist or none.
    imported = 0
    for item in validated:
        d = item.model_dump()
        vat = vat_amount(d["amount_try"], d["vat_rate"])
        twv = total_with_vat(d["amount_try"], d["vat_rate"])
        if d.get("payment_status") == "paid" and not d.get("amount_paid_try"):
            d["amount_paid_try"] = twv
        entry = CostEntry(
            project_id=project.id, company_id=user.company_id, created_by=user.id,
            vat_amount_try=vat, total_with_vat_try=twv, **d,
        )
        db.add(entry)
        db.flush()
        record_audit(
            db, company_id=user.company_id, user_id=user.id, table_name="cost_entries",
            record_id=entry.id, action="INSERT", new_values=snapshot(entry),
        )
        imported += 1
    db.commit()
    return success({"imported": imported, "skipped": 0})
