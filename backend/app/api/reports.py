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
