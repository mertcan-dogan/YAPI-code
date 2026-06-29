"""CR-011-C — agent ACTION tools (propose-only).

GOVERNING INVARIANT (§0.2.1, §3.1, §7): the agent NEVER writes a business/
financial row directly. Every action tool here only *proposes* — it builds a
validated, company-scoped change and inserts a **pending** ``ApprovalRequest``
via the existing approvals lifecycle (``approvals.create_request``). The actual
mutation happens elsewhere, and only after a human approves the request through
``/approvals`` (``approvals.apply_request``). There is no direct-mutation path in
this module — grep it: the only writes are ``approvals.create_request`` (a
pending proposal) + ``db.commit`` of that proposal.

Each tool returns a confirmation object ("öneri oluşturuldu — onayınızı
bekliyor") carrying the pending request id + a ``proposed_action`` block the
agent surfaces to the UI as an Onayla/Reddet card.
"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.responses import APIError
from app.services import approvals as approvals_service
from app.services.studio import creators as studio_creators
from app.services.studio.catalog import validate_spec as validate_report_spec


class ActionError(Exception):
    """Raised when a proposed action is invalid (bad target, missing field…).
    The executor turns this into a Turkish tool_result error for the model."""


# Turkish labels for the proposed-action card / approvals list.
ACTION_KIND_LABELS = {
    "agent_reminder": "Hatırlatıcı (AI önerisi)",
    "agent_flag_invoice": "İnceleme İşareti (AI önerisi)",
    "agent_task": "Görev (AI önerisi)",
    # CR-035 — agent-authored Report Studio report / dashboard proposals (DORMANT
    # after CR-039: never produced anymore; kept for any in-flight pending rows).
    "agent_create_report": "Rapor (AI önerisi)",
    "agent_create_dashboard": "Pano (AI önerisi)",
    # CR-039 — conversational authoring DRAFTS (no DB write; user creates via OLUŞTUR).
    "draft_report": "Rapor Taslağı",
    "draft_dashboard": "Pano Taslağı",
    # CR-044 — a Skill (Beceri) DRAFT: a saved file-recipe; user saves via OLUŞTUR.
    "draft_skill": "Beceri Taslağı",
}

_PENDING_MESSAGE = (
    "Öneri oluşturuldu — onayınızı bekliyor. Onaylayana kadar hiçbir değişiklik "
    "yapılmaz; /approvals (Onaylar) sayfasından onaylayabilir veya reddedebilirsiniz."
)


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _confirmation(req, extra: dict | None = None) -> dict:
    """Build the model-facing result + the UI proposed_action block. The agent is
    instructed to say 'öneri oluşturuldu', never 'yaptım'.

    CR-035: ``extra`` enriches the proposed_action with the proposed artifact
    (a report ``spec`` or a dashboard's ``widgets``) so the chat card can render a
    LIVE PREVIEW without a second fetch. It is display-only — the authoritative copy
    is in ``req.payload`` and the row is still created only on human approval."""
    pa = {
        "request_id": str(req.id),
        "kind": req.kind,
        "kind_label": ACTION_KIND_LABELS.get(req.kind, req.kind),
        "description": req.description,
        "amount_try": str(req.amount_try) if req.amount_try is not None else None,
        "project_id": str(req.project_id) if req.project_id else None,
        "status": req.status,  # always "pending"
        "deep_link": "/approvals",
    }
    if extra:
        pa.update(extra)
    return {
        "ok": True,
        "proposed": True,
        "status": "pending",
        "message": _PENDING_MESSAGE,
        "proposed_action": pa,
    }


def _create_and_commit(db: Session, **kw):
    """Insert the pending proposal and commit it so it persists regardless of how
    the rest of the agent turn ends. Only a proposal row is written — no business
    mutation (those happen on human approval via approvals.apply_request)."""
    req = approvals_service.create_request(db, proposed_by_agent=True, **kw)
    db.commit()
    return req


def _draft(kind: str, title: str, fields: dict) -> dict:
    """CR-039 — build a DRAFT proposed_action with NO DB write at all: no
    ``ApprovalRequest``, no ``request_id``, no commit. The agent writes nothing;
    the user creates their own report/pano by pressing OLUŞTUR, which calls the
    existing ``POST /studio/reports|/studio/dashboards`` as themselves
    (``CurrentUser``). This STRENGTHENS the CR-011 invariant — authoring no longer
    writes even a pending proposal. The draft rides the existing
    ``proposed_actions[]`` channel; the FE keys on ``kind`` (no ``request_id`` ⇒ a
    draft card, not an approvals card)."""
    return {
        "ok": True,
        "proposed": True,
        "status": "draft",
        "message": "Taslak hazır — sohbette düzenleyebilir veya Oluştur'a basabilirsiniz.",
        "proposed_action": {
            "kind": kind,
            "kind_label": ACTION_KIND_LABELS.get(kind, kind),
            "title": title,
            **fields,
        },
    }


# --------------------------------------------------------------------------- #
# Action tool: propose_reminder
# --------------------------------------------------------------------------- #
def propose_reminder(db: Session, company_id, user_id, *, title: str,
                     note: str | None = None, due_date=None, project_id=None) -> dict:
    """Propose an in-app reminder (lands in the bell on approval). Propose-only."""
    title = (title or "").strip()
    if not title:
        raise ActionError("Hatırlatıcı için bir başlık gerekli.")
    due = _parse_date(due_date)
    desc = f"Hatırlatıcı önerisi: {title}"
    if due:
        desc += f" (son tarih {due.isoformat()})"
    req = _create_and_commit(
        db,
        company_id=company_id,
        project_id=_as_uuid(project_id),
        kind="agent_reminder",
        target_table="notifications",
        target_id=None,
        payload={"title": title, "body": (note or "").strip() or None,
                 "due_date": due.isoformat() if due else None},
        description=desc,
        requested_by=user_id,
    )
    return _confirmation(req)


# --------------------------------------------------------------------------- #
# Action tool: propose_flag_invoice (flag a hakediş / cost record for review)
# --------------------------------------------------------------------------- #
def propose_flag_invoice(db: Session, company_id, user_id, *, target_kind: str,
                         target_id, reason: str, project_id=None) -> dict:
    """Propose flagging a client invoice or cost entry for review. Propose-only:
    on approval an AIAlert review finding is created on that record."""
    if target_kind not in ("client_invoice", "cost_entry"):
        raise ActionError("target_kind 'client_invoice' veya 'cost_entry' olmalı.")
    reason = (reason or "").strip()
    if not reason:
        raise ActionError("İşaretleme için bir gerekçe gerekli.")
    tid = _as_uuid(target_id)
    if tid is None:
        raise ActionError("Geçerli bir hedef kayıt kimliği (target_id) gerekli.")

    # Validate the target exists AND belongs to this company (never flag across
    # companies or a non-existent record).
    if target_kind == "client_invoice":
        row = db.execute(
            select(ClientInvoice).where(
                ClientInvoice.id == tid, ClientInvoice.company_id == company_id,
                ClientInvoice.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        label = f"Fatura {row.invoice_number}" if row else None
        pid = row.project_id if row else None
    else:
        row = db.execute(
            select(CostEntry).where(
                CostEntry.id == tid, CostEntry.company_id == company_id,
                CostEntry.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        label = f"Maliyet {row.supplier_name}" if row else None
        pid = row.project_id if row else None
    if row is None:
        raise ActionError("İşaretlenecek kayıt bulunamadı.")

    req = _create_and_commit(
        db,
        company_id=company_id,
        project_id=pid or _as_uuid(project_id),
        kind="agent_flag_invoice",
        target_table="client_invoices" if target_kind == "client_invoice" else "cost_entries",
        target_id=tid,
        payload={"source_type": target_kind, "reason": reason,
                 "title": f"İnceleme: {label}"},
        description=f"İnceleme önerisi: {label} — {reason}",
        requested_by=user_id,
    )
    return _confirmation(req)


# --------------------------------------------------------------------------- #
# Action tool: propose_followup_task (raise a follow-up / approval request)
# --------------------------------------------------------------------------- #
def propose_followup_task(db: Session, company_id, user_id, *, title: str,
                          note: str | None = None, project_id=None) -> dict:
    """Propose a follow-up task / approval request for a human to action.
    Propose-only: becomes an in-app notification task on approval."""
    title = (title or "").strip()
    if not title:
        raise ActionError("Görev için bir başlık gerekli.")
    req = _create_and_commit(
        db,
        company_id=company_id,
        project_id=_as_uuid(project_id),
        kind="agent_task",
        target_table="notifications",
        target_id=None,
        payload={"title": title, "body": (note or "").strip() or None},
        description=f"Görev önerisi: {title}",
        requested_by=user_id,
    )
    return _confirmation(req)


# --------------------------------------------------------------------------- #
# CR-035 — Action tool: propose_report (author a Report Studio report)
# --------------------------------------------------------------------------- #
def propose_report(db: Session, company_id, user_id, *, title: str, spec,
                   visibility: str = "private", labels=None, project_id=None) -> dict:
    """CR-039 — DRAFT a Report Studio report from an agent-built CR-032 spec.
    Validates the spec against the catalog (on an invalid spec it raises
    ``ActionError`` and NO draft is returned — the model gets the error and
    corrects), then returns a ``draft_report`` proposed-action carrying the spec.
    It writes NOTHING (no ``ApprovalRequest``, no Report row). The Report is created
    only by the user's explicit OLUŞTUR click (``POST /studio/reports`` as
    themselves), which strengthens the CR-011 never-writes invariant."""
    title = (title or "").strip()
    if not title:
        raise ActionError("Rapor için bir başlık gerekli.")
    if not isinstance(spec, dict):
        raise ActionError("Rapor tanımı (spec) bir nesne olmalı.")
    try:
        validate_report_spec(spec)
    except APIError as exc:
        raise ActionError(
            f"Rapor tanımı geçersiz: {exc.message} "
            "Yalnızca studio_catalog'daki metrik/boyut kimliklerini kullan."
        )
    vis = visibility if visibility in ("private", "company") else "private"
    # CR-039 — DRAFT: validation done above; write NOTHING. The user creates their
    # own report via OLUŞTUR (POST /studio/reports as themselves).
    return _draft("draft_report", title,
                  {"spec": spec, "visibility": vis, "labels": labels})


# --------------------------------------------------------------------------- #
# CR-035 — Action tool: propose_dashboard (author a Report Studio pano)
# --------------------------------------------------------------------------- #
def propose_dashboard(db: Session, company_id, user_id, *, title: str, widgets,
                      date_range=None, comparison=None, filters=None,
                      visibility: str = "private", labels=None, project_id=None) -> dict:
    """CR-039 — DRAFT a Report Studio dashboard (pano) of widgets. Validates every
    widget (envelope + each data widget's inner spec against the catalog +
    report-widget viewability + unique ids; on an invalid deck it raises
    ``ActionError`` and NO draft is returned), then returns a ``draft_dashboard``
    proposed-action carrying the validated widgets. It writes NOTHING. The Dashboard
    is created only by the user's explicit OLUŞTUR click (``POST /studio/dashboards``
    as themselves) — strengthening the CR-011 never-writes invariant."""
    title = (title or "").strip()
    if not title:
        raise ActionError("Pano için bir başlık gerekli.")
    if not isinstance(widgets, list) or not widgets:
        raise ActionError("Pano için en az bir widget gerekli.")
    try:
        normalised = studio_creators.validate_widgets(db, company_id, user_id, widgets)
    except APIError as exc:
        raise ActionError(
            f"Pano tanımı geçersiz: {exc.message} "
            "Yalnızca studio_catalog'daki metrik/boyut kimliklerini kullan."
        )
    widgets_json = [w.model_dump(mode="json") for w in normalised]
    vis = visibility if visibility in ("private", "company") else "private"
    # CR-039 — DRAFT: validation done above; write NOTHING. The user creates their
    # own pano via OLUŞTUR (POST /studio/dashboards as themselves).
    return _draft("draft_dashboard", title,
                  {"widgets": widgets_json, "date_range": date_range,
                   "comparison": comparison, "filters": filters,
                   "visibility": vis, "labels": labels})


# --------------------------------------------------------------------------- #
# CR-044 — Action tool: propose_skill (DRAFT a reusable file recipe / Beceri)
# --------------------------------------------------------------------------- #
def propose_skill(db: Session, company_id, user_id, *, name, widgets,
                  format: str = "xlsx", instruction: str = "", date_range=None,
                  visibility: str = "private", labels=None, project_scope=None,
                  project_id=None) -> dict:
    """CR-044 — DRAFT a Skill (Beceri): a saved, reusable *deliverable recipe* that
    generates an Excel/PDF from LIVE data on demand. The agent decides STRUCTURE
    only — it composes a dashboard-shaped ``plan`` ({format, title, widgets[],
    date_range?}) from validated CR-032 widget specs (exactly as it drafts a pano).
    EVERY figure is produced by the trusted engine (``run_spec``) at RUN time, never
    by the model — so this carries the agent's no-fabrication invariant.

    Validates the widgets against the catalog (on an invalid plan it raises
    ``ActionError`` and NO draft is returned), then returns a ``draft_skill``
    proposed-action carrying the compiled plan. It writes NOTHING (no DB row). The
    Skill is created only by the user's explicit OLUŞTUR / "Beceri olarak kaydet"
    click (``POST /skills`` as themselves) — the CR-039/CR-011 never-writes invariant.
    """
    name = (name or "").strip()
    if not name:
        raise ActionError("Beceri için bir ad gerekli.")
    fmt = format if format in ("xlsx", "pdf") else "xlsx"
    if not isinstance(widgets, list) or not widgets:
        raise ActionError("Beceri için en az bir widget (bölüm) gerekli.")
    # CR-047 — a project-scoped skill: the resolved project id (from list_projects).
    # Validate it is a real, viewable project in THIS company (the agent resolves the
    # name; this enforces it can never store a bad/cross-company scope). At run time
    # the scope is merged into every widget's filters, so the whole report is about
    # that project. If the agent couldn't resolve the name it must ASK, not pass junk.
    scope = None
    if project_scope:
        scope_id = _as_uuid(project_scope)
        if scope_id is None:
            raise ActionError("Geçersiz proje kimliği.")
        proj = db.execute(
            select(Project).where(
                Project.id == scope_id,
                Project.company_id == company_id,
                Project.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if proj is None:
            raise ActionError("Proje bulunamadı — list_projects ile doğrula veya kullanıcıya sor.")
        scope = str(scope_id)
    try:
        normalised = studio_creators.validate_widgets(db, company_id, user_id, widgets)
    except APIError as exc:
        raise ActionError(
            f"Beceri planı geçersiz: {exc.message} "
            "Yalnızca studio_catalog'daki metrik/boyut kimliklerini kullan."
        )
    widgets_json = [w.model_dump(mode="json") for w in normalised]
    vis = visibility if visibility in ("private", "company") else "private"
    # The compiled, runnable plan — a dashboard-shaped spec saved + re-run each time.
    # ``project_scope`` (CR-047) rides the JSONB (no migration); the run merges it.
    plan = {
        "format": fmt,
        "title": name,
        "widgets": widgets_json,
        "date_range": date_range,
        "project_scope": scope,
    }
    # CR-044 — DRAFT: validation done above; write NOTHING. The user saves their own
    # Skill via OLUŞTUR (POST /skills as themselves). instruction falls back to the
    # name when blank so the draft stays consistent with SkillCreate (min_length=1)
    # and can always be saved.
    return _draft("draft_skill", name, {
        "plan": plan,
        "format": fmt,
        "instruction": (instruction or "").strip() or name,
        "visibility": vis,
        "labels": labels,
    })


def _as_uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
