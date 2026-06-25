"""Project closeout router — the Turkish acceptance lifecycle + frozen report.

ALL stage actions (geçici kabul / kesin hesap / kesin kabul) and reopen are gated
to ROLE_DIRECTOR (``DirectorUser``) and audited. The GET endpoints are read-only
for every role (non-directors see status, no actions). The freeze happens in the
service at Kesin Hesap; the PDF is regenerated on demand from the frozen dict.
"""
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, DirectorUser, InvoiceCreatorUser
from app.models.company import Company
from app.responses import APIError, success
from app.schemas.closeout import CloseoutOut, CloseoutStageIn
from app.services import closeout as closeout_service
from app.services.access import get_company_project
from app.services.audit import record_audit, snapshot

router = APIRouter(tags=["closeout"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _serialize(db: Session, project, closeout) -> dict:
    """Closeout read model + summary (off the frozen report) + a staleness flag."""
    if closeout is None:
        return {
            "closeout": None,
            "project_status": project.status,
            "summary": None,
            "report_frozen": False,
            "report_stale": False,
        }
    return {
        "closeout": CloseoutOut.model_validate(closeout).model_dump(mode="json"),
        "project_status": project.status,
        "summary": closeout_service.summary_from_report(closeout),
        "report_frozen": closeout.frozen_at is not None,
        "report_stale": closeout_service.report_is_stale(db, project, closeout),
    }


def _audit_closeout(db, request, user, project, closeout, action, old=None) -> None:
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="project_closeouts",
        record_id=closeout.id, action=action, old_values=old, new_values=snapshot(closeout),
        ip_address=_ip(request),
    )


def _audit_project_status(db, request, user, project, old) -> None:
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="projects",
        record_id=project.id, action="UPDATE", old_values=old, new_values=snapshot(project),
        ip_address=_ip(request),
    )


# --- Stage transitions (director-only, audited) -----------------------------
@router.post("/projects/{project_id}/closeout/gecici-kabul")
def gecici_kabul(
    project_id: uuid.UUID,
    payload: CloseoutStageIn,
    request: Request,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    old_project = snapshot(project)
    closeout = closeout_service.start_gecici_kabul(db, project, payload.date, user.id)
    _audit_closeout(db, request, user, project, closeout, "INSERT")
    _audit_project_status(db, request, user, project, old_project)
    db.commit()
    db.refresh(closeout)
    db.refresh(project)
    return success(_serialize(db, project, closeout))


@router.post("/projects/{project_id}/closeout/kesin-hesap")
def kesin_hesap(
    project_id: uuid.UUID,
    payload: CloseoutStageIn,
    request: Request,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    closeout = closeout_service.get_active_closeout(db, project)
    old = snapshot(closeout) if closeout else None
    closeout = closeout_service.advance_kesin_hesap(db, project, company, payload.date)
    _audit_closeout(db, request, user, project, closeout, "UPDATE", old=old)
    db.commit()
    db.refresh(closeout)
    return success(_serialize(db, project, closeout))


@router.post("/projects/{project_id}/closeout/kesin-kabul")
def kesin_kabul(
    project_id: uuid.UUID,
    payload: CloseoutStageIn,
    request: Request,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    closeout = closeout_service.get_active_closeout(db, project)
    old = snapshot(closeout) if closeout else None
    closeout = closeout_service.advance_kesin_kabul(db, project, payload.date)
    _audit_closeout(db, request, user, project, closeout, "UPDATE", old=old)
    db.commit()
    db.refresh(closeout)
    return success(_serialize(db, project, closeout))


@router.post("/projects/{project_id}/reopen")
def reopen(
    project_id: uuid.UUID,
    request: Request,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    old_project = snapshot(project)
    closeout = closeout_service.get_active_closeout(db, project)
    old = snapshot(closeout) if closeout else None
    closeout = closeout_service.reopen(db, project, user.id)
    _audit_closeout(db, request, user, project, closeout, "UPDATE", old=old)
    _audit_project_status(db, request, user, project, old_project)
    db.commit()
    db.refresh(project)
    return success(_serialize(db, project, None))


# --- Reads (all roles; read-only) -------------------------------------------
@router.get("/projects/{project_id}/closeout")
def get_closeout(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    closeout = closeout_service.get_active_closeout(db, project)
    return success(_serialize(db, project, closeout))


@router.get("/projects/{project_id}/closeouts")
def list_closeouts(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    rows = closeout_service.list_closeouts(db, project)
    data = []
    for c in rows:
        item = CloseoutOut.model_validate(c).model_dump(mode="json")
        item["summary"] = closeout_service.summary_from_report(c)
        item["report_frozen"] = c.frozen_at is not None
        data.append(item)
    return success(data, meta={"total": len(data)})


def _frozen_pdf_response(project, closeout) -> Response:
    """Regenerate the PDF on demand from the FROZEN dict — never recompute live."""
    if closeout is None or not closeout.report_data:
        raise APIError(404, "NOT_FROZEN", "Proje sonu raporu henüz dondurulmadı (kesin hesap gerekli)")
    try:
        from app.services.reports import _project_report_pdf

        pdf = _project_report_pdf(closeout.report_data)
    except Exception as exc:  # ReportLab/render issues
        raise APIError(500, "REPORT_ERROR", f"Rapor oluşturulamadı: {exc}")
    filename = f"proje-sonu-raporu-{project.project_code}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/closeout/report.pdf")
def closeout_report_pdf(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,  # Site managers cannot export (Section 3.2), as in reports.py
    db: Session = Depends(get_db),
):
    """PDF of the CURRENT active closeout's frozen report (404 if not yet frozen)."""
    project = get_company_project(db, project_id, user)
    closeout = closeout_service.get_active_closeout(db, project)
    return _frozen_pdf_response(project, closeout)


@router.get("/projects/{project_id}/closeouts/{closeout_id}/report.pdf")
def closeout_archive_report_pdf(
    project_id: uuid.UUID,
    closeout_id: uuid.UUID,
    user: InvoiceCreatorUser,  # Site managers cannot export (Section 3.2)
    db: Session = Depends(get_db),
):
    """PDF of a SPECIFIC (possibly archived) closeout's frozen report.

    Company + project scoped: the row must belong to this project (and the user's
    company, enforced by get_company_project + the explicit company filter).
    """
    project = get_company_project(db, project_id, user)
    closeout = db.execute(
        select(closeout_service.ProjectCloseout).where(
            closeout_service.ProjectCloseout.id == closeout_id,
            closeout_service.ProjectCloseout.project_id == project.id,
            closeout_service.ProjectCloseout.company_id == project.company_id,
        )
    ).scalar_one_or_none()
    if closeout is None:
        raise APIError(404, "NOT_FOUND", "Kapanış kaydı bulunamadı")
    return _frozen_pdf_response(project, closeout)
