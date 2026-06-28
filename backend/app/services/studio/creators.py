"""CR-035 — shared Report/Dashboard creators (factored out of api/studio.py).

The SAME creation + validation logic now backs BOTH:
  * the human endpoints — ``POST /studio/reports`` / ``POST /studio/dashboards``; and
  * the agent-proposal appliers — ``approvals._apply_agent_create_report`` /
    ``_apply_agent_create_dashboard``, which run ONLY after a human approves a
    pending ``ApprovalRequest`` (the CR-011 invariant — the agent never reaches
    this code, it only *proposes*).

``company_id`` / ``owner_id`` / ``created_by`` are ALWAYS supplied by the caller
from a trusted source — the authenticated user (endpoint) or ``req.company_id`` /
``req.requested_by`` on the approval row (applier). They are NEVER read from a
request/payload body, so a proposal can only ever create a row in the requester's
own company. Validation (``catalog.validate_spec`` for reports; the widget
validator for dashboards) runs here, so both paths reject an invalid spec
identically and NO row is written when validation fails. These creators
``db.add`` + ``db.flush`` but never ``commit`` — the caller owns the transaction.
"""
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.dashboard import Dashboard
from app.models.report import Report
from app.responses import APIError
from app.schemas.dashboard import WidgetSpec
from app.services.studio.catalog import validate_spec

# Defense-in-depth caps / normalisation shared by both the endpoint and the agent
# applier (a future payload source can't store junk or a pathological deck).
MAX_DASHBOARD_WIDGETS = 50
_VALID_VISIBILITY = ("private", "company")


def _clamp_visibility(value) -> str:
    return value if value in _VALID_VISIBILITY else "private"


def report_viewable_select(company_id, user_id):
    """Reports ``user_id`` may VIEW within ``company_id``: own (any visibility) +
    company-visible, excluding soft-deleted. Mirrors ``api/studio._viewable_q`` but
    decoupled from the request ``user`` object so the agent/applier path reuses it."""
    return select(Report).where(
        Report.company_id == company_id,
        Report.is_deleted.is_(False),
        or_(Report.owner_id == user_id, Report.visibility == "company"),
    )


def _as_widget_spec(w) -> WidgetSpec:
    """Normalise a widget (a dict from a stored payload, or an already-parsed
    ``WidgetSpec``) into a validated ``WidgetSpec`` — enforcing the envelope
    invariant (exactly one payload per type)."""
    if isinstance(w, WidgetSpec):
        return w
    try:
        return WidgetSpec.model_validate(w)
    except Exception as exc:  # pydantic ValidationError / type errors
        raise APIError(422, "VALIDATION_ERROR", f"Geçersiz widget: {str(exc)[:120]}", "widgets")


def validate_widgets(db: Session, company_id, user_id, widgets) -> list[WidgetSpec]:
    """Validate a dashboard's widget array before persisting — envelope (via
    ``WidgetSpec``) + each kpi/chart/table widget's inner CR-032 spec against the
    catalog + each report widget's ``report_id`` viewable by the creator + unique
    widget ids. Accepts dicts or ``WidgetSpec`` objects; returns the normalised
    ``WidgetSpec`` list. Raises ``APIError(422)`` on any violation."""
    if widgets and len(widgets) > MAX_DASHBOARD_WIDGETS:
        raise APIError(422, "VALIDATION_ERROR",
                       f"Bir panoda en fazla {MAX_DASHBOARD_WIDGETS} widget olabilir", "widgets")
    seen: set[str] = set()
    normalised: list[WidgetSpec] = []
    for raw in widgets or []:
        w = _as_widget_spec(raw)
        if w.id in seen:
            raise APIError(422, "VALIDATION_ERROR", f"Yinelenen widget kimliği: {w.id!r}", "widgets")
        seen.add(w.id)
        if w.type in ("kpi", "chart", "table"):
            validate_spec(w.spec)
        elif w.type == "report":
            ref = None
            if w.report_id is not None:
                ref = db.execute(
                    report_viewable_select(company_id, user_id).where(Report.id == w.report_id)
                ).scalar_one_or_none()
            if ref is None:
                raise APIError(
                    422, "VALIDATION_ERROR",
                    "Rapor widget'ı görüntülenebilir bir rapora başvurmalı", "widgets",
                )
        normalised.append(w)
    return normalised


def create_report(
    db: Session, *, company_id, owner_id, created_by, title, spec,
    visibility: str = "private", labels=None,
) -> Report:
    """Validate (catalog) + construct a ``Report`` (``db.add`` + ``flush``; caller
    commits). The single creation path shared by the endpoint and the agent
    applier — change report-creation logic here, once."""
    validate_spec(spec)
    report = Report(
        company_id=company_id,
        owner_id=owner_id,
        created_by=created_by,
        title=title,
        spec=spec,
        visibility=_clamp_visibility(visibility),
        labels=labels,
    )
    db.add(report)
    db.flush()
    return report


def create_dashboard(
    db: Session, *, company_id, owner_id, created_by, title, widgets,
    date_range=None, comparison=None, filters=None,
    visibility: str = "private", labels=None,
) -> Dashboard:
    """Validate (widgets) + construct a ``Dashboard`` (``db.add`` + ``flush``;
    caller commits). ``widgets`` may be dicts or ``WidgetSpec`` objects; they are
    stored as JSON dicts. Report-widget viewability is checked against ``owner_id``
    (the creator). The single creation path shared by the endpoint + applier."""
    normalised = validate_widgets(db, company_id, owner_id, widgets)
    dashboard = Dashboard(
        company_id=company_id,
        owner_id=owner_id,
        created_by=created_by,
        title=title,
        widgets=[w.model_dump(mode="json") for w in normalised],
        date_range=date_range,
        comparison=comparison,
        filters=filters,
        visibility=_clamp_visibility(visibility),
        labels=labels,
    )
    db.add(dashboard)
    db.flush()
    return dashboard
