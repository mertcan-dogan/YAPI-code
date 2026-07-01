"""Reports router (Section 2.5, 4.9)."""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import InvoiceCreatorUser
from app.models.company import Company
from app.responses import APIError
from app.services.access import get_company_project

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/project/{project_id}")
def project_report(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,  # Site managers cannot export (Section 3.2)
    db: Session = Depends(get_db),
):
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    try:
        from app.services.reports import render_project_report

        pdf = render_project_report(db, project, company)
    except Exception as exc:  # ReportLab/render issues
        raise APIError(500, "REPORT_ERROR", f"Rapor oluşturulamadı: {exc}")

    filename = f"proje-durum-{project.project_code}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file_response(content: bytes, media: str, filename: str) -> Response:
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _premade_report(db, project, company, *, pdf_fn, xlsx_fn, slug, fmt):
    """CR-048 — shared dispatch for the premade reports. ``fmt`` is pdf|xlsx (xlsx
    only when ``xlsx_fn`` is given). Read-only; render errors → a clean 500."""
    if fmt not in ("pdf", "xlsx"):
        raise APIError(422, "BAD_FORMAT", "Geçersiz biçim (pdf veya xlsx)")
    if fmt == "xlsx" and xlsx_fn is None:
        raise APIError(422, "BAD_FORMAT", "Bu rapor yalnızca PDF olarak sunulur")
    try:
        if fmt == "xlsx":
            return _file_response(xlsx_fn(db, project, company), _XLSX_MEDIA,
                                  f"{slug}-{project.project_code}.xlsx")
        return _file_response(pdf_fn(db, project, company), "application/pdf",
                              f"{slug}-{project.project_code}.pdf")
    except APIError:
        raise
    except Exception as exc:  # ReportLab/openpyxl render issues
        raise APIError(500, "REPORT_ERROR", f"Rapor oluşturulamadı: {exc}")


@router.get("/cost/{project_id}")
def cost_report(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
    fmt: str = "pdf",
):
    """CR-048 — Maliyet Detay Raporu (PDF or Excel)."""
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    from app.services.reports_premade import render_cost_report, render_cost_xlsx

    return _premade_report(db, project, company, pdf_fn=render_cost_report,
                           xlsx_fn=render_cost_xlsx, slug="maliyet-detay", fmt=fmt)


@router.get("/invoice/{project_id}")
def invoice_report(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    """CR-048 — Hakediş Raporu (PDF; revenue-model-aware per CR-047)."""
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    from app.services.reports_premade import render_invoice_report

    return _premade_report(db, project, company, pdf_fn=render_invoice_report,
                           xlsx_fn=None, slug="hakedis", fmt="pdf")


@router.get("/subcontractor/{project_id}")
def subcontractor_report(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
):
    """CR-048 — Alt Yüklenici Raporu (PDF)."""
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    from app.services.reports_premade import render_subcontractor_report

    return _premade_report(db, project, company, pdf_fn=render_subcontractor_report,
                           xlsx_fn=None, slug="alt-yuklenici", fmt="pdf")


@router.get("/cashflow/{project_id}")
def cashflow_report(
    project_id: uuid.UUID,
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
    fmt: str = "pdf",
):
    """CR-048 — Nakit Akış Raporu (PDF or Excel; full project span)."""
    project = get_company_project(db, project_id, user)
    company = db.get(Company, user.company_id)
    from app.services.reports_premade import render_cashflow_report, render_cashflow_xlsx

    return _premade_report(db, project, company, pdf_fn=render_cashflow_report,
                           xlsx_fn=render_cashflow_xlsx, slug="nakit-akis", fmt=fmt)


@router.get("/management-pack")
def management_pack(
    user: InvoiceCreatorUser,
    db: Session = Depends(get_db),
    period: str | None = None,
):
    """CR-003-K: monthly management pack PDF (7 pages)."""
    company = db.get(Company, user.company_id)
    period_label = period or "Bu Ay"
    try:
        from app.services.reports import render_management_pack

        pdf = render_management_pack(db, company, period_label)
    except Exception as exc:
        raise APIError(500, "REPORT_ERROR", f"Rapor oluşturulamadı: {exc}")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="aylik-yonetim-paketi.pdf"'},
    )
