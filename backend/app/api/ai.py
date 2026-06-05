"""AI router (Section 2.5, 5). Daily briefing, alerts, invoice extraction."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, DirectorOrPMUser
from app.models.ai_alert import AIAlert
from app.responses import APIError, success
from app.services import ai as ai_service
from app.services.access import get_company_project
from app.services.alert_engine import analyze_project
from app.services.financials import project_financials

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_PDF_BYTES = 10 * 1024 * 1024


@router.post("/analyze-project/{project_id}")
def analyze(project_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    project = get_company_project(db, project_id, user)
    created = analyze_project(db, project)
    return success({"alerts_created": created, "ai_available": ai_service.is_available()})


@router.get("/alerts")
def list_alerts(user: CurrentUser, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(AIAlert)
        .where(AIAlert.company_id == user.company_id)
        .order_by(AIAlert.created_at.desc())
    ).scalars().all()
    visible = []
    for a in rows:
        if a.is_dismissed and (a.dismissed_until is None or a.dismissed_until > now):
            continue
        visible.append(
            {
                "id": str(a.id),
                "project_id": str(a.project_id) if a.project_id else None,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title_tr": a.title_tr,
                "body_tr": a.body_tr,
                "reasoning": a.reasoning,
                "recommended_action": a.recommended_action,
                "is_actioned": a.is_actioned,
                "created_at": a.created_at.isoformat(),
            }
        )
    return success(visible, meta={"total": len(visible), "ai_available": ai_service.is_available()})


@router.put("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    alert = db.execute(
        select(AIAlert).where(AIAlert.id == alert_id, AIAlert.company_id == user.company_id)
    ).scalar_one_or_none()
    if alert is None:
        raise APIError(404, "NOT_FOUND", "Uyarı bulunamadı")
    alert.is_dismissed = True
    alert.dismissed_by = user.id
    # Dismissed alerts are not re-shown for 7 days (Section 5.5).
    alert.dismissed_until = datetime.now(timezone.utc) + timedelta(days=7)
    db.commit()
    return success({"id": str(alert_id), "message": "Uyarı kapatıldı"})


@router.get("/daily-briefing")
def daily_briefing(user: CurrentUser, db: Session = Depends(get_db)):
    from app.models.project import Project

    projects = db.execute(
        select(Project).where(
            Project.company_id == user.company_id,
            Project.is_deleted.is_(False),
            Project.status == "active",
        )
    ).scalars().all()
    summaries = []
    for p in projects:
        f = project_financials(db, p)
        summaries.append(
            {
                "name": p.name,
                "margin_pct": float(f["margin_pct"]),
                "rag_status": f["rag_status"],
                "rag_reason_tr": f["rag_reason_tr"],
                "overdue_count": f["overdue_count"],
                "net_cash_position_try": float(f["net_cash_position_try"]),
            }
        )
    items = ai_service.daily_briefing(summaries)
    return success(items, meta={"ai_available": ai_service.is_available()})


@router.post("/extract-invoice")
async def extract_invoice(
    user: DirectorOrPMUser,
    file: UploadFile = File(...),
):
    if file.content_type not in ("application/pdf",):
        raise APIError(422, "VALIDATION_ERROR", "Sadece PDF yükleyebilirsiniz", field="file")
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Dosya en fazla 10MB olabilir", field="file")
    try:
        fields = ai_service.extract_invoice(data)
    except ai_service.AIUnavailable:
        raise APIError(503, "AI_UNAVAILABLE", ai_service.AI_UNAVAILABLE_MESSAGE)
    return success({"extracted": fields, "source": "ai"})
