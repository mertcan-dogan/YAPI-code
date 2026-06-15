"""AI router (Section 2.5, 5). Daily briefing, alerts, invoice extraction."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.db import get_db
from app.deps import CurrentUser, DirectorOrPMUser
from app.models.ai_alert import AIAlert
from app.models.project import Project
from app.responses import APIError, success
from app.services import ai as ai_service
from app.services.access import get_company_project
from app.services.alert_engine import analyze_project
from app.services.financials import forecast_at_completion, project_financials

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_PDF_BYTES = 10 * 1024 * 1024


class AssistantQuestion(BaseModel):
    question: str
    project_id: uuid.UUID | None = None


class AgentMessage(BaseModel):
    role: str  # "user" | "assistant" (Anthropic shape; mapped from the store in CR-007-F)
    content: str


class AgentRequest(BaseModel):
    messages: list[AgentMessage]
    project_id: uuid.UUID | None = None


def _active_projects(db: Session, company_id):
    return db.execute(
        select(Project).where(
            Project.company_id == company_id, Project.is_deleted.is_(False), Project.status == "active"
        )
    ).scalars().all()


@router.post("/assistant")
def assistant(payload: AssistantQuestion, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-003-H: natural-language financial Q&A scoped to the user's company."""
    from app.models.company import Company

    company = db.get(Company, user.company_id)
    context: dict = {"company": company.name if company else "", "soru": payload.question}

    if payload.project_id:
        project = get_company_project(db, payload.project_id, user)  # RLS/scoping
        f = project_financials(db, project)
        fac = forecast_at_completion(db, project)
        context["proje"] = {
            "ad": project.name,
            "sozlesme_degeri": str(f["contract_value_try"]),
            "guncel_marj_pct": str(f["margin_pct"]),
            "tahmini_final_marj_pct": fac["forecast_final_margin_pct"],
            "net_nakit": str(f["net_cash_position_try"]),
            "vadesi_gecmis_adet": f["overdue_count"],
            "rag": f["rag_status"],
        }
    else:
        rows = []
        for p in _active_projects(db, user.company_id):
            f = project_financials(db, p)
            rows.append({
                "ad": p.name, "marj_pct": str(f["margin_pct"]),
                "net_nakit": str(f["net_cash_position_try"]),
                "vadesi_gecmis_adet": f["overdue_count"], "rag": f["rag_status"],
            })
        context["projeler"] = rows

    answer = ai_service.assistant_answer(payload.question, context)
    return success({"answer": answer, "data_points": context, "generated_at": datetime.now(timezone.utc).isoformat()})


@router.post("/agent")
def agent(payload: AgentRequest, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-007-B/E: agentic tool-use loop. The model calls read-only, company-scoped
    tools (which compute via SQL) and narrates the results in Turkish. Rate-limited
    to 10 req/min/user; one ai_query_log row per successful request; graceful
    degradation on Claude error/timeout."""
    from app.config import settings
    from app.middleware.limits import enforce_user_limit
    from app.services import agent as agent_service

    if not payload.messages:
        raise APIError(422, "VALIDATION_ERROR", "En az bir mesaj gerekli")

    # CR-007-E: 10 req/min/user (raises APIError 429 in Turkish).
    enforce_user_limit(user.id, "ai_agent", settings.ai_agent_rate_per_minute)

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    try:
        result = agent_service.run_agent(
            db, user.company_id, messages, project_id=payload.project_id, user_id=user.id
        )
    except ai_service.AIUnavailable:
        return success(agent_service.degraded_response())
    return success(result)


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
                "feedback": a.feedback,
                "created_at": a.created_at.isoformat(),
            }
        )
    return success(visible, meta={"total": len(visible), "ai_available": ai_service.is_available()})


class AlertFeedback(BaseModel):
    feedback: str  # useful | wrong | irrelevant


@router.put("/alerts/{alert_id}/feedback")
def alert_feedback(alert_id: uuid.UUID, payload: AlertFeedback, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-003-M: record useful/wrong/irrelevant feedback on an alert."""
    if payload.feedback not in ("useful", "wrong", "irrelevant"):
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz geri bildirim")
    alert = db.execute(
        select(AIAlert).where(AIAlert.id == alert_id, AIAlert.company_id == user.company_id)
    ).scalar_one_or_none()
    if alert is None:
        raise APIError(404, "NOT_FOUND", "Uyarı bulunamadı")
    alert.feedback = payload.feedback
    db.commit()
    return success({"id": str(alert_id), "feedback": payload.feedback})


@router.post("/analyze-all")
def analyze_all(user: CurrentUser, db: Session = Depends(get_db)):
    """CR-003-M: re-run the alert engine across all active projects."""
    total = 0
    for p in db.execute(
        select(Project).where(
            Project.company_id == user.company_id, Project.is_deleted.is_(False), Project.status == "active"
        )
    ).scalars().all():
        total += len(analyze_project(db, p))
    return success({"alerts_created": total})


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
