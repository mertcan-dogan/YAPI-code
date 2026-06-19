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
from app.services import approvals as approvals_service


class ActionError(Exception):
    """Raised when a proposed action is invalid (bad target, missing field…).
    The executor turns this into a Turkish tool_result error for the model."""


# Turkish labels for the proposed-action card / approvals list.
ACTION_KIND_LABELS = {
    "agent_reminder": "Hatırlatıcı (AI önerisi)",
    "agent_flag_invoice": "İnceleme İşareti (AI önerisi)",
    "agent_task": "Görev (AI önerisi)",
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


def _confirmation(req) -> dict:
    """Build the model-facing result + the UI proposed_action block. The agent is
    instructed to say 'öneri oluşturuldu', never 'yaptım'."""
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


def _as_uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
