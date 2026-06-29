"""AI router (Section 2.5, 5). Daily briefing, alerts, invoice extraction."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.db import get_db
from app.deps import CurrentUser, DirectorOrPMUser, DirectorUser
from app.models.ai_alert import AIAlert
from app.models.ai_feedback import AIFeedback
from app.models.ai_query_log import AIQueryLog
from app.models.project import Project
from app.models.user import User
from app.responses import APIError, success
from app.services import ai as ai_service
from app.services.access import get_company_project
from app.services.alert_engine import analyze_project
from app.services.audit import record_audit
from app.services.financials import forecast_at_completion, project_financials

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_PDF_BYTES = 10 * 1024 * 1024
# CR-024-A: reject pathologically long feedback comments.
MAX_FEEDBACK_COMMENT = 2000


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class AssistantQuestion(BaseModel):
    question: str
    project_id: uuid.UUID | None = None


class AgentMessage(BaseModel):
    role: str  # "user" | "assistant" (Anthropic shape; mapped from the store in CR-007-F)
    content: str


class AgentRequest(BaseModel):
    messages: list[AgentMessage]
    project_id: uuid.UUID | None = None
    # CR-011-B §2.1 — optional domain scope (gider|gelir|finans|hakedis|belge).
    # null/unknown = the general agent. Validated leniently: an unknown value is
    # treated as genel rather than rejected.
    scope: str | None = None
    # CR-035 — "Bu rapor hakkında sor": ground a read-only Q&A in a saved report.
    # The server loads the report (company-scoped; 404 if not viewable), runs its
    # spec for fresh totals/rows, and injects that as read-only system context.
    report_id: uuid.UUID | None = None
    # CR-039 — the active authoring DRAFT the user is refining ({kind, spec|widgets,
    # title}). Threaded back so the agent edits the real spec instead of rebuilding
    # from prose. Request-only context (mirrors scope/report_id) — never persisted,
    # no schema/migration. The agent still writes nothing; creation is the user's
    # explicit OLUŞTUR click.
    draft: dict | None = None


def _report_grounding(db: Session, user, report_id: uuid.UUID) -> str:
    """CR-035 — build a compact, read-only Turkish grounding block for "Bu rapor
    hakkında sor": the report's spec + a fresh server-run of its result (trusted
    totals/rows). Company-scoped via ``_get_viewable`` (404 if the caller can't see
    it). The numbers come from the server's own ``run_spec`` — never the client."""
    import json

    from app.api.studio import _get_viewable
    from app.services.studio.engine import run_spec

    report = _get_viewable(db, user, report_id)  # 404 if cross-company / private-stranger
    spec = report.spec or {}
    parts = [
        f"Kullanıcı şu kayıtlı rapor hakkında soru soruyor: «{report.title}». "
        "Yanıtını YALNIZCA bu raporun verilerine dayandır; yeni bir rapor/pano ÖNERME.",
        f"Spec — metrikler: {spec.get('metrics')}; boyutlar: {spec.get('dimensions') or '—'}; "
        f"görsel: {spec.get('viz', 'table')}; tarih: {spec.get('date_range') or 'varsayılan'}.",
    ]
    try:
        result = run_spec(db, user.company_id, spec)
        totals = (result.get("totals") or {}).get("metrics") or {}
        rows = result.get("rows") or []
        parts.append("Toplamlar: " + json.dumps(totals, ensure_ascii=False, default=str))
        parts.append(f"Satır sayısı: {len(rows)}.")
        if rows:
            parts.append(
                "Satırlar (örnek): "
                + json.dumps(rows[:15], ensure_ascii=False, default=str)[:2000]
            )
    except Exception:  # grounding is best-effort; degrade to spec-only context
        parts.append("(Rapor sonucu şu an çalıştırılamadı; spec'e göre yanıtla.)")
    return "\n".join(parts)


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
def agent(
    payload: AgentRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
    stream: int = Query(0),
):
    """CR-007-B/E: agentic tool-use loop. The model calls read-only, company-scoped
    tools (which compute via SQL) and narrates the results in Turkish. Rate-limited
    to 10 req/min/user; one ai_query_log row per successful request; graceful
    degradation on Claude error/timeout.

    CR-011-A §1.1: ``?stream=1`` returns an SSE stream — incremental ``delta`` text
    events + ``step`` events as tools run + one ``final`` event carrying the same
    structured payload (charts/citations/log). On any streaming error it falls back
    so the answer is never lost; with no model available it emits a degraded final."""
    from app.config import settings
    from app.middleware.limits import enforce_user_limit
    from app.services import agent as agent_service

    if not payload.messages:
        raise APIError(422, "VALIDATION_ERROR", "En az bir mesaj gerekli")

    # CR-007-E: 10 req/min/user (raises APIError 429 in Turkish).
    enforce_user_limit(user.id, "ai_agent", settings.ai_agent_rate_per_minute)

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    # CR-035 — "Bu rapor hakkında sor": ground the answer in a saved report. Built
    # synchronously so a bad/cross-company report_id 404s BEFORE any streaming starts.
    extra_context = _report_grounding(db, user, payload.report_id) if payload.report_id else ""

    if stream:
        import anyio
        from fastapi.responses import StreamingResponse

        company_id, uid, pid = user.company_id, user.id, payload.project_id
        scope = payload.scope
        draft = payload.draft  # CR-039 — active authoring draft (refine context)

        # ASYNC generator (CR-011 streaming fix): an async iterator is driven in
        # the event loop, NOT via Starlette's iterate_in_threadpool — so it never
        # parks a threadpool worker (a sync StreamingResponse generator can leak a
        # worker when the client doesn't drain it). The blocking agent loop is
        # pulled one event at a time off the loop via anyio.to_thread, keeping the
        # loop responsive; the generator is always closed on completion/disconnect.
        async def event_stream():
            gen = agent_service.run_agent_stream(
                db, company_id, messages, project_id=pid, user_id=uid, scope=scope,
                extra_context=extra_context, draft=draft,
            )
            sentinel = object()

            def _next():
                try:
                    return next(gen)
                except StopIteration:
                    return sentinel

            try:
                while True:
                    ev = await anyio.to_thread.run_sync(_next)
                    if ev is sentinel:
                        break
                    yield agent_service.sse_event(ev)
            except ai_service.AIUnavailable:
                # Never lose the answer: emit a degraded final event (§1.1 fallback).
                yield agent_service.sse_event(
                    {"type": "final", "data": agent_service.degraded_response()}
                )
            finally:
                gen.close()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = agent_service.run_agent(
            db, user.company_id, messages, project_id=payload.project_id,
            user_id=user.id, scope=payload.scope, extra_context=extra_context,
            draft=payload.draft,
        )
    except ai_service.AIUnavailable:
        return success(agent_service.degraded_response())
    return success(result)


class AgentAnalysisExport(BaseModel):
    """CR-011-C §3.2 — a finished agent analysis to render to PDF/Excel. The
    payload is exactly what the agent already returned to the UI (no re-run)."""
    answer_markdown: str
    charts: list[dict] = []
    citations: list[dict] = []
    title: str | None = None
    question: str | None = None


@router.post("/agent/export")
def agent_export(
    payload: AgentAnalysisExport,
    user: CurrentUser,
    db: Session = Depends(get_db),
    fmt: str = Query("pdf", pattern="^(pdf|excel)$"),
):
    """CR-011-C §3.2: render an agent analysis (answer text + chart(s) +
    citations) to a downloadable PDF or Excel, reusing services/reports.py.
    Company-scoped (the header uses the caller's company)."""
    from fastapi.responses import Response

    from app.models.company import Company
    from app.services import reports

    if not (payload.answer_markdown or "").strip():
        raise APIError(422, "VALIDATION_ERROR", "Analiz metni gerekli", field="answer_markdown")

    company = db.get(Company, user.company_id)
    analysis = {
        "title": payload.title or "Yapı AI Analizi",
        "question": payload.question,
        "answer_markdown": payload.answer_markdown,
        "charts": payload.charts,
        "citations": payload.citations,
    }
    try:
        if fmt == "excel":
            data = reports.render_agent_analysis_excel(company, analysis)
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="yapi-ai-analiz.xlsx"'},
            )
        data = reports.render_agent_analysis_pdf(company, analysis)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="yapi-ai-analiz.pdf"'},
        )
    except Exception as exc:  # render failure -> Turkish error, never a 500 stack
        raise APIError(500, "REPORT_ERROR", f"Analiz dışa aktarılamadı: {exc}")


class AgentFeedbackIn(BaseModel):
    query_log_id: uuid.UUID | None = None
    question: str
    rating: str  # "up" | "down"
    comment: str | None = None


@router.post("/agent/feedback")
def agent_feedback(
    payload: AgentFeedbackIn, user: CurrentUser, request: Request, db: Session = Depends(get_db)
):
    """CR-024-A: record a 👍/👎 (+ optional comment) on an agent answer.

    Append-only and company-scoped; mirrors the alert-feedback write. It never
    mutates/regenerates the answer (§0.2.4) — it only stores the signal. Free-text
    comments stay in this company-scoped row and are not forwarded anywhere (§0.2.5).
    """
    if payload.rating not in ("up", "down"):
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz değerlendirme")

    question = (payload.question or "").strip()
    if not question:
        raise APIError(422, "VALIDATION_ERROR", "Soru gerekli", field="question")

    comment = (payload.comment or "").strip() or None
    if comment and len(comment) > MAX_FEEDBACK_COMMENT:
        raise APIError(422, "VALIDATION_ERROR", "Yorum en fazla 2000 karakter olabilir", field="comment")

    # Only link a query_log_id that belongs to this company; otherwise store null
    # (never link across companies, never 404 — feedback is still worth keeping).
    log_id = None
    if payload.query_log_id is not None:
        log_id = db.execute(
            select(AIQueryLog.id).where(
                AIQueryLog.id == payload.query_log_id,
                AIQueryLog.company_id == user.company_id,
            )
        ).scalar_one_or_none()

    fb = AIFeedback(
        company_id=user.company_id,
        user_id=user.id,
        ai_query_log_id=log_id,
        question=question,
        rating=payload.rating,
        comment=comment,
    )
    db.add(fb)
    db.flush()
    # Audit the signal, NOT the free-text comment (privacy minimization §0.2.5).
    record_audit(
        db, company_id=user.company_id, user_id=user.id, table_name="ai_feedback",
        record_id=fb.id, action="INSERT",
        new_values={"rating": fb.rating, "ai_query_log_id": str(log_id) if log_id else None},
        ip_address=_ip(request),
    )
    db.commit()
    return success({"id": str(fb.id)})


@router.get("/agent/feedback")
def list_agent_feedback(
    user: DirectorUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """CR-024-A: directors-only review of recent agent feedback (company-scoped,
    newest first). For a future 'ne işe yaramıyor' review. Cross-user, so it is
    restricted to directors even though PMs may use the agent."""
    total = db.execute(
        select(func.count()).select_from(AIFeedback).where(AIFeedback.company_id == user.company_id)
    ).scalar_one()
    rows = db.execute(
        select(AIFeedback)
        .where(AIFeedback.company_id == user.company_id)
        .order_by(AIFeedback.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()
    names = {
        u.id: u.full_name
        for u in db.execute(select(User).where(User.company_id == user.company_id)).scalars().all()
    }
    data = [
        {
            "id": str(f.id),
            "question": f.question,
            "rating": f.rating,
            "comment": f.comment,
            "created_at": f.created_at.isoformat(),
            "user": names.get(f.user_id),
        }
        for f in rows
    ]
    return success(data, meta={"total": total, "page": page, "per_page": per_page})


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
                # CR-022: record linkage for the Finans Güvence view (NULL on
                # legacy health alerts — the view filters on dedup_key presence).
                "source_type": a.source_type,
                "source_id": str(a.source_id) if a.source_id else None,
                "dedup_key": a.dedup_key,
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


@router.post("/assurance/scan")
def assurance_scan(user: CurrentUser, db: Session = Depends(get_db)):
    """CR-022-B: run the read-only assurance rule pack for the caller's company and
    upsert anomaly findings (dedup-aware, respects dismissals). Returns the honest
    scan summary {scanned, found, total_found, created}. Same permission as
    analyze-project/analyze-all (any authenticated user)."""
    from app.services import assurance

    return success(assurance.scan_company(db, user.company_id))


@router.post("/analyze-all")
def analyze_all(user: CurrentUser, db: Session = Depends(get_db)):
    """CR-003-M: re-run the alert engine across all active projects.
    CR-022-B: also refresh the company's assurance findings in the same pass."""
    from app.services import assurance

    total = 0
    for p in db.execute(
        select(Project).where(
            Project.company_id == user.company_id, Project.is_deleted.is_(False), Project.status == "active"
        )
    ).scalars().all():
        total += len(analyze_project(db, p))
    assurance_summary = assurance.scan_company(db, user.company_id)
    return success({"alerts_created": total, "assurance": assurance_summary})


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
