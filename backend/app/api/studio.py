"""Report Studio API.

CR-032 §5 — the read-only catalog + ad-hoc run endpoints.
CR-033 — saved-report persistence (CRUD + duplicate + run + export).

Every endpoint is ``CurrentUser``-gated and company-scoped: ``company_id`` ALWAYS
comes from the authenticated user, NEVER from the request body. Saved reports are
soft-deleted (``is_deleted``); visibility is "private" (owner-only) or "company"
(all same-company users may view). Edit/delete is owner-or-director only. The
engine and catalog (``run_spec`` / ``validate_spec``) are reused unchanged — the
AI agent never reaches these write paths (CR-011 holds).
"""
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.constants import ROLE_DIRECTOR
from app.db import get_db
from app.deps import CurrentUser
from app.models.company import Company
from app.models.dashboard import Dashboard
from app.models.report import Report
from app.responses import APIError, success
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardListItem,
    DashboardOut,
    DashboardUpdate,
)
from app.schemas.report import ReportCreate, ReportListItem, ReportOut, ReportUpdate
from app.services.studio import creators
from app.services.studio.catalog import get_catalog_public, validate_spec
from app.services.studio.engine import run_spec
from app.services.studio.export import studio_export, studio_export_dashboard

router = APIRouter(tags=["studio"])

EXPORT_FORMATS = ("pdf", "xlsx", "csv")


def _company_name(db: Session, user) -> str | None:
    """CR-046 — the caller's company name for the Excel header band (read-only)."""
    co = db.get(Company, user.company_id)
    return co.name if co else None


# --------------------------------------------------------------------------- #
# CR-032 §5 — catalog + ad-hoc run
# --------------------------------------------------------------------------- #
@router.get("/studio/catalog")
def studio_catalog(user: CurrentUser):
    """The dimension/metric catalog (id/label/type/group/description/status only)
    that drives the CR-033 picker. Cacheable; no per-company data."""
    return success(get_catalog_public())


@router.post("/studio/run")
def studio_run(user: CurrentUser, spec: dict = Body(...), db: Session = Depends(get_db)):
    """Run a Spec (§2) and return the result shape (§2). A malformed spec raises
    ``APIError(422)`` (handled by the global error middleware). The engine is
    read-only and scoped to ``user.company_id``."""
    return success(run_spec(db, user.company_id, spec))


# --------------------------------------------------------------------------- #
# CR-033 — saved reports
# --------------------------------------------------------------------------- #
def _report_out(report: Report, user) -> dict:
    return ReportOut(
        id=report.id,
        title=report.title,
        spec=report.spec,
        visibility=report.visibility,
        labels=report.labels,
        owner_id=report.owner_id,
        created_by=report.created_by,
        created_at=report.created_at,
        updated_at=report.updated_at,
        is_owner=(report.owner_id == user.id),
    ).model_dump(mode="json")


def _viewable_q(user):
    """Reports the user may VIEW: own (any visibility) + company-visible. Always
    company-scoped and excludes soft-deleted rows. Another user's `private`
    report is simply not selected — no existence leak."""
    return select(Report).where(
        Report.company_id == user.company_id,
        Report.is_deleted.is_(False),
        or_(Report.owner_id == user.id, Report.visibility == "company"),
    )


def _get_viewable(db: Session, user, report_id: uuid.UUID) -> Report:
    report = db.execute(_viewable_q(user).where(Report.id == report_id)).scalar_one_or_none()
    if report is None:
        raise APIError(404, "NOT_FOUND", "Rapor bulunamadı")
    return report


def _get_editable(db: Session, user, report_id: uuid.UUID) -> Report:
    """Reports the user may EDIT/DELETE. Fetch predicate: in-company, not deleted,
    and (owner OR company-visible OR director). Then gate: a non-director,
    non-owner is forbidden (403). Net effect — private+stranger → 404 (invisible),
    company+stranger-non-director → 403, owner/director → ok."""
    stmt = select(Report).where(
        Report.id == report_id,
        Report.company_id == user.company_id,
        Report.is_deleted.is_(False),
    )
    if user.role != ROLE_DIRECTOR:
        # Directors reach any in-company report; others only own + company-visible.
        stmt = stmt.where(or_(Report.owner_id == user.id, Report.visibility == "company"))
    report = db.execute(stmt).scalar_one_or_none()
    if report is None:
        raise APIError(404, "NOT_FOUND", "Rapor bulunamadı")
    if user.role != ROLE_DIRECTOR and report.owner_id != user.id:
        raise APIError(403, "FORBIDDEN", "Bu raporu düzenleme yetkiniz yok")
    return report


@router.get("/studio/reports")
def list_reports(user: CurrentUser, q: str | None = None, db: Session = Depends(get_db)):
    """Saved reports the user may view, newest-edited first. Optional ``q`` does a
    case-insensitive title contains-match."""
    stmt = _viewable_q(user)
    if q:
        stmt = stmt.where(Report.title.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Report.updated_at.desc())).scalars().all()
    items = [
        ReportListItem(
            id=r.id,
            title=r.title,
            owner_id=r.owner_id,
            visibility=r.visibility,
            updated_at=r.updated_at,
            labels=r.labels,
            viz=(r.spec or {}).get("viz", "table"),
        ).model_dump(mode="json")
        for r in rows
    ]
    return success(items)


@router.post("/studio/reports")
def create_report(body: ReportCreate, user: CurrentUser, db: Session = Depends(get_db)):
    """Save a new report. The spec is validated against the catalog (422 if bad).
    company_id/owner_id/created_by come from the authenticated user. CR-035: the
    create logic is factored into ``creators.create_report`` so the agent-proposal
    applier shares the exact same path."""
    report = creators.create_report(
        db,
        company_id=user.company_id,
        owner_id=user.id,
        created_by=user.id,
        title=body.title,
        spec=body.spec,
        visibility=body.visibility,
        labels=body.labels,
    )
    db.commit()
    db.refresh(report)
    return success(_report_out(report, user))


@router.get("/studio/reports/{report_id}")
def get_report(report_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    report = _get_viewable(db, user, report_id)
    return success(_report_out(report, user))


@router.patch("/studio/reports/{report_id}")
def update_report(
    report_id: uuid.UUID, body: ReportUpdate, user: CurrentUser, db: Session = Depends(get_db)
):
    report = _get_editable(db, user, report_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("spec") is not None:
        validate_spec(changes["spec"])
    # Non-nullable columns are only overwritten when a non-null value is supplied.
    for field in ("title", "spec", "visibility"):
        if changes.get(field) is not None:
            setattr(report, field, changes[field])
    if "labels" in changes:  # labels is nullable — an explicit null clears it
        report.labels = changes["labels"]
    report.updated_by = user.id
    db.commit()
    db.refresh(report)
    return success(_report_out(report, user))


@router.delete("/studio/reports/{report_id}")
def delete_report(report_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    report = _get_editable(db, user, report_id)
    report.is_deleted = True
    report.deleted_at = datetime.now(timezone.utc)
    report.updated_by = user.id
    db.commit()
    return success({"deleted": True})


@router.post("/studio/reports/{report_id}/duplicate")
def duplicate_report(report_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Copy a viewable report into a new PRIVATE report owned by the caller."""
    src = _get_viewable(db, user, report_id)
    report = Report(
        company_id=user.company_id,
        owner_id=user.id,
        created_by=user.id,
        title=f"{src.title} (kopya)",
        spec=deepcopy(src.spec),
        visibility="private",
        labels=deepcopy(src.labels) if src.labels is not None else None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return success(_report_out(report, user))


@router.post("/studio/reports/{report_id}/run")
def run_report(report_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Execute a saved report's spec — identical to POST /studio/run on that spec,
    company-scoped to the caller. Read-only."""
    report = _get_viewable(db, user, report_id)
    return success(run_spec(db, user.company_id, report.spec))


@router.post("/studio/reports/{report_id}/export")
def export_report(
    report_id: uuid.UUID,
    user: CurrentUser,
    format: str = Query("pdf"),
    db: Session = Depends(get_db),
) -> Response:
    """Export a saved report as pdf/xlsx/csv. Runs the spec read-only and streams a
    file attachment. Unknown format → 422; cross-company / private-stranger id →
    404 (via ``_get_viewable``)."""
    report = _get_viewable(db, user, report_id)
    if format not in EXPORT_FORMATS:
        raise APIError(422, "INVALID_FORMAT", "Geçersiz dışa aktarma biçimi (pdf, xlsx veya csv)")
    result = run_spec(db, user.company_id, report.spec)
    return studio_export(result, format, report.title, viz=(report.spec or {}).get("viz"),
                         company=_company_name(db, user))


# --------------------------------------------------------------------------- #
# CR-034 — saved dashboards (panolar)
# --------------------------------------------------------------------------- #
# A pano deck may only be exported as a multi-widget pdf/xlsx — csv (a single
# table) is the per-report export, so it is rejected here.
DASHBOARD_EXPORT_FORMATS = ("pdf", "xlsx")


def _dashboard_out(dashboard: Dashboard, user) -> dict:
    return DashboardOut(
        id=dashboard.id,
        title=dashboard.title,
        widgets=dashboard.widgets or [],
        date_range=dashboard.date_range,
        comparison=dashboard.comparison,
        filters=dashboard.filters,
        visibility=dashboard.visibility,
        labels=dashboard.labels,
        owner_id=dashboard.owner_id,
        created_by=dashboard.created_by,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
        is_owner=(dashboard.owner_id == user.id),
    ).model_dump(mode="json")


def _dashboard_viewable_q(user):
    """Dashboards the user may VIEW: own (any visibility) + company-visible. Always
    company-scoped and excludes soft-deleted rows. Another user's `private` pano is
    simply not selected — no existence leak."""
    return select(Dashboard).where(
        Dashboard.company_id == user.company_id,
        Dashboard.is_deleted.is_(False),
        or_(Dashboard.owner_id == user.id, Dashboard.visibility == "company"),
    )


def _get_dashboard_viewable(db: Session, user, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = db.execute(
        _dashboard_viewable_q(user).where(Dashboard.id == dashboard_id)
    ).scalar_one_or_none()
    if dashboard is None:
        raise APIError(404, "NOT_FOUND", "Pano bulunamadı")
    return dashboard


def _get_dashboard_editable(db: Session, user, dashboard_id: uuid.UUID) -> Dashboard:
    """Dashboards the user may EDIT/DELETE — identical logic to ``_get_editable``:
    fetch in-company + not-deleted + (owner OR company-visible OR director), then
    gate so a non-director non-owner is forbidden (403). Net effect — private+
    stranger → 404 (invisible), company+stranger-non-director → 403, owner/director
    → ok (404-before-403, no existence leak)."""
    stmt = select(Dashboard).where(
        Dashboard.id == dashboard_id,
        Dashboard.company_id == user.company_id,
        Dashboard.is_deleted.is_(False),
    )
    if user.role != ROLE_DIRECTOR:
        stmt = stmt.where(or_(Dashboard.owner_id == user.id, Dashboard.visibility == "company"))
    dashboard = db.execute(stmt).scalar_one_or_none()
    if dashboard is None:
        raise APIError(404, "NOT_FOUND", "Pano bulunamadı")
    if user.role != ROLE_DIRECTOR and dashboard.owner_id != user.id:
        raise APIError(403, "FORBIDDEN", "Bu panoyu düzenleme yetkiniz yok")
    return dashboard


def _resolve_report_widget(db: Session, user, report_id):
    """NON-RAISING company-scoped viewable lookup for a report-widget's target.
    Returns the Report or None (cross-company / private-stranger / soft-deleted /
    malformed id) — the caller degrades a None to ``{"unavailable": True}``, never
    raising and never leaking another tenant's data."""
    if report_id is None:
        return None
    try:
        rid = report_id if isinstance(report_id, uuid.UUID) else uuid.UUID(str(report_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return db.execute(_viewable_q(user).where(Report.id == rid)).scalar_one_or_none()


def _validate_widgets(db: Session, user, widgets) -> None:
    """Validate a dashboard's widget array before persisting. CR-035: delegates to
    ``creators.validate_widgets`` (the shared validator used by both this endpoint
    and the agent-proposal applier) so the rules stay in one place — each kpi/chart/
    table widget's inner CR-032 spec against the catalog, each report widget's
    ``report_id`` viewable by the creator, and unique widget ids (422 on any)."""
    creators.validate_widgets(db, user.company_id, user.id, widgets)


def _global_merge(spec: dict, dashboard: Dashboard) -> dict:
    """FOUNDER OVERRIDE of the spec — global vs widget merge. Inject the
    dashboard-level ``date_range``/``comparison``/``filters`` into a deepcopy of the
    target ``spec`` ONLY where that key is absent or None in the target; a key the
    target already supplies (present AND non-null) WINS (widget/own-spec overrides
    global). Applies to BOTH data widgets and report widgets."""
    merged = deepcopy(spec) if spec else {}
    for key in ("date_range", "comparison", "filters"):
        global_val = getattr(dashboard, key)
        if global_val is not None and merged.get(key) is None:
            merged[key] = deepcopy(global_val)
    return merged


def _run_dashboard_batch(db: Session, user, dashboard: Dashboard) -> dict:
    """Render every kpi/chart/table/report widget on the deck → {widget_id:
    result-or-status}. Text widgets are omitted (the FE renders their content).
    Read-only and company-scoped (``company_id`` from auth). A report widget
    pointing at a report the caller can't view degrades to ``{"unavailable": True}``
    — never raising, never 500, never leaking another tenant's data."""
    results: dict = {}
    for w in dashboard.widgets or []:
        wtype = w.get("type")
        wid = w.get("id")
        if wtype in ("kpi", "chart", "table"):
            merged = _global_merge(w.get("spec") or {}, dashboard)
            results[wid] = run_spec(db, user.company_id, merged)
        elif wtype == "report":
            ref = _resolve_report_widget(db, user, w.get("report_id"))
            if ref is None:
                results[wid] = {"unavailable": True}
            else:
                merged = _global_merge(ref.spec or {}, dashboard)
                results[wid] = run_spec(db, user.company_id, merged)
        # text widgets carry no data → omitted from the batch result.
    return results


@router.get("/studio/dashboards")
def list_dashboards(user: CurrentUser, q: str | None = None, db: Session = Depends(get_db)):
    """Saved dashboards the user may view, newest-edited first. Optional ``q`` does
    a case-insensitive title contains-match."""
    stmt = _dashboard_viewable_q(user)
    if q:
        stmt = stmt.where(Dashboard.title.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Dashboard.updated_at.desc())).scalars().all()
    items = [
        DashboardListItem(
            id=d.id,
            title=d.title,
            owner_id=d.owner_id,
            visibility=d.visibility,
            updated_at=d.updated_at,
            labels=d.labels,
            widget_count=len(d.widgets or []),
        ).model_dump(mode="json")
        for d in rows
    ]
    return success(items)


@router.post("/studio/dashboards")
def create_dashboard(body: DashboardCreate, user: CurrentUser, db: Session = Depends(get_db)):
    """Save a new dashboard. Every kpi/chart/table widget's spec is validated against
    the catalog, each report widget must reference a viewable report, and widget ids
    must be unique (422 on any violation). company_id/owner_id/created_by come from
    the authenticated user — never the body. CR-035: the create logic is factored
    into ``creators.create_dashboard`` so the agent-proposal applier shares it."""
    dashboard = creators.create_dashboard(
        db,
        company_id=user.company_id,
        owner_id=user.id,
        created_by=user.id,
        title=body.title,
        widgets=body.widgets,
        date_range=body.date_range,
        comparison=body.comparison,
        filters=body.filters,
        visibility=body.visibility,
        labels=body.labels,
    )
    db.commit()
    db.refresh(dashboard)
    return success(_dashboard_out(dashboard, user))


@router.get("/studio/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    dashboard = _get_dashboard_viewable(db, user, dashboard_id)
    return success(_dashboard_out(dashboard, user))


@router.patch("/studio/dashboards/{dashboard_id}")
def update_dashboard(
    dashboard_id: uuid.UUID,
    body: DashboardUpdate,
    user: CurrentUser,
    db: Session = Depends(get_db),
):
    dashboard = _get_dashboard_editable(db, user, dashboard_id)
    changes = body.model_dump(exclude_unset=True)
    if body.widgets is not None:
        _validate_widgets(db, user, body.widgets)
        dashboard.widgets = [w.model_dump(mode="json") for w in body.widgets]
    # Non-nullable columns are only overwritten when a non-null value is supplied.
    for field in ("title", "visibility"):
        if changes.get(field) is not None:
            setattr(dashboard, field, changes[field])
    # Nullable JSONB columns — an explicit null clears them.
    for field in ("date_range", "comparison", "filters", "labels"):
        if field in changes:
            setattr(dashboard, field, changes[field])
    dashboard.updated_by = user.id
    db.commit()
    db.refresh(dashboard)
    return success(_dashboard_out(dashboard, user))


@router.delete("/studio/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    dashboard = _get_dashboard_editable(db, user, dashboard_id)
    dashboard.is_deleted = True
    dashboard.deleted_at = datetime.now(timezone.utc)
    dashboard.updated_by = user.id
    db.commit()
    return success({"deleted": True})


@router.post("/studio/dashboards/{dashboard_id}/duplicate")
def duplicate_dashboard(dashboard_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Copy a viewable dashboard into a new PRIVATE dashboard owned by the caller."""
    src = _get_dashboard_viewable(db, user, dashboard_id)
    dashboard = Dashboard(
        company_id=user.company_id,
        owner_id=user.id,
        created_by=user.id,
        title=f"{src.title} (kopya)",
        widgets=deepcopy(src.widgets) if src.widgets is not None else [],
        date_range=deepcopy(src.date_range) if src.date_range is not None else None,
        comparison=deepcopy(src.comparison) if src.comparison is not None else None,
        filters=deepcopy(src.filters) if src.filters is not None else None,
        visibility="private",
        labels=deepcopy(src.labels) if src.labels is not None else None,
    )
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return success(_dashboard_out(dashboard, user))


@router.post("/studio/dashboards/{dashboard_id}/run")
def run_dashboard(dashboard_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    """Batch-render every data/report widget on the deck → {widget_id:
    result-or-status}. Read-only and company-scoped; one call renders the canvas."""
    dashboard = _get_dashboard_viewable(db, user, dashboard_id)
    return success(_run_dashboard_batch(db, user, dashboard))


@router.post("/studio/dashboards/{dashboard_id}/export")
def export_dashboard(
    dashboard_id: uuid.UUID,
    user: CurrentUser,
    format: str = Query("pdf"),
    db: Session = Depends(get_db),
) -> Response:
    """Export a dashboard deck as pdf/xlsx (csv is rejected — it maps to a single
    table, which is the per-report export). Runs the same read-only batch as /run,
    then streams a file attachment. Unknown/csv format → 422; cross-company /
    private-stranger id → 404 (via ``_get_dashboard_viewable``)."""
    dashboard = _get_dashboard_viewable(db, user, dashboard_id)
    if format not in DASHBOARD_EXPORT_FORMATS:
        raise APIError(422, "INVALID_FORMAT", "Pano için geçersiz dışa aktarma biçimi (pdf veya xlsx)")
    results = _run_dashboard_batch(db, user, dashboard)
    return studio_export_dashboard(dashboard.widgets or [], results, dashboard.title, format,
                                   company=_company_name(db, user))
