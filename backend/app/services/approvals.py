"""Approval-workflow service (CR-004-N).

Centralises the generic approval-request lifecycle for triggers that don't have a
``pending_approval`` flag on their own row. Cost-entry creation still uses the
``cost_entries.pending_approval`` flag (CR-003-J); everything else goes through
``approval_requests``.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.approval_request import ApprovalRequest
from app.models.company import Company

# kind -> the Company toggle that gates it.
_TOGGLE = {
    "budget_change": "require_budget_approval",
    "subcontractor_change": "require_subcontractor_approval",
    "cost_deletion": "require_deletion_approval",
    "variation_approval": "require_variation_approval",
}


def is_required(company: Company | None, kind: str) -> bool:
    """Whether `kind` needs director approval for this company."""
    if company is None or not company.approvals_enabled:
        return False
    attr = _TOGGLE.get(kind)
    return bool(attr and getattr(company, attr, False))


def create_request(
    db: Session,
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID | None,
    kind: str,
    target_table: str,
    target_id: uuid.UUID | None,
    payload: dict | None,
    description: str,
    amount_try=None,
    requested_by: uuid.UUID,
    proposed_by_agent: bool = False,
) -> ApprovalRequest:
    req = ApprovalRequest(
        company_id=company_id,
        project_id=project_id,
        kind=kind,
        target_table=target_table,
        target_id=target_id,
        payload=payload,
        description=description,
        amount_try=amount_try,
        status="pending",
        requested_by=requested_by,
        proposed_by_agent=proposed_by_agent,
    )
    db.add(req)
    db.flush()
    return req


def apply_request(db: Session, req: ApprovalRequest) -> None:
    """Apply the requested change to its target row. Called on approval."""
    if req.kind == "budget_change":
        _apply_budget_change(db, req)
    elif req.kind == "subcontractor_change":
        _apply_subcontractor_change(db, req)
    elif req.kind == "cost_deletion":
        _apply_cost_deletion(db, req)
    elif req.kind == "variation_approval":
        _apply_variation_approval(db, req)
    # CR-011-C — agent-proposed actions. These run ONLY here, after a human has
    # approved the pending request; the agent itself never reaches this code.
    elif req.kind in ("agent_reminder", "agent_task"):
        _apply_agent_notification(db, req)
    elif req.kind == "agent_flag_invoice":
        _apply_agent_flag_invoice(db, req)
    # CR-012 Template A — auto-file: create the proposed cost/client-invoice record
    # using the SAME creation logic as document-capture/confirm. Runs only here,
    # after a human approves; the automation itself never writes a record.
    elif req.kind == "agent_file_document":
        _apply_agent_file_document(db, req)


def mark_decided(req: ApprovalRequest, *, user_id: uuid.UUID, status: str, reason: str | None = None) -> None:
    req.status = status
    req.decided_by = user_id
    req.decided_at = datetime.now(timezone.utc)
    if reason:
        req.reason = reason


# --- per-kind appliers --------------------------------------------------------
def _apply_budget_change(db: Session, req: ApprovalRequest) -> None:
    from app.models.budget_line_item import BudgetLineItem

    payload = req.payload or {}
    category = payload.get("category")
    changes = payload.get("changes", {})
    line = db.get(BudgetLineItem, req.target_id) if req.target_id else None
    if line is None and category:
        line = BudgetLineItem(project_id=req.project_id, company_id=req.company_id, cost_category=category)
        db.add(line)
        db.flush()
    if line is not None:
        for k, v in changes.items():
            setattr(line, k, v)
        db.flush()


def _apply_subcontractor_change(db: Session, req: ApprovalRequest) -> None:
    from app.models.subcontractor import Subcontractor

    sub = db.get(Subcontractor, req.target_id) if req.target_id else None
    if sub is not None:
        for k, v in (req.payload or {}).get("changes", {}).items():
            setattr(sub, k, v)
        db.flush()


def _apply_cost_deletion(db: Session, req: ApprovalRequest) -> None:
    from app.models.cost_entry import CostEntry

    cost = db.get(CostEntry, req.target_id) if req.target_id else None
    if cost is not None and not cost.is_deleted:
        cost.is_deleted = True
        cost.deleted_at = datetime.now(timezone.utc)
        db.flush()


def _apply_variation_approval(db: Session, req: ApprovalRequest) -> None:
    from app.api.variations import _sync_category_budget
    from app.calculations.money import D
    from app.models.variation import Variation

    v = db.get(Variation, req.target_id) if req.target_id else None
    if v is None:
        return
    payload = req.payload or {}
    v.status = "approved"
    if payload.get("approved_value_try") is not None:
        v.approved_value_try = D(payload["approved_value_try"])
    elif v.approved_value_try is None:
        v.approved_value_try = v.value_try
    if payload.get("approved_date"):
        from datetime import date as _date

        v.approved_date = _date.fromisoformat(payload["approved_date"])
    db.flush()
    _sync_category_budget(db, v.project_id, v.company_id, v.cost_category)


# --- CR-011-C agent-proposed appliers ----------------------------------------
def _apply_agent_notification(db: Session, req: ApprovalRequest) -> None:
    """An approved agent reminder/task becomes an in-app notification (CR-006-C
    bell). Scoped to the user who triggered the agent (requested_by)."""
    from app.models.notification import Notification

    payload = req.payload or {}
    note = Notification(
        company_id=req.company_id,
        user_id=req.requested_by,
        title=(payload.get("title") or req.description or "Hatırlatıcı")[:200],
        body=payload.get("body"),
        notification_type="ai_alert",
        severity=payload.get("severity") or "medium",
        related_project_id=req.project_id,
    )
    db.add(note)
    db.flush()


def _apply_agent_flag_invoice(db: Session, req: ApprovalRequest) -> None:
    """An approved 'flag for review' becomes a manual AIAlert review finding on
    the target record — so it shows up in Finans Güvence and is dismissible."""
    from app.models.ai_alert import AIAlert

    payload = req.payload or {}
    source_type = payload.get("source_type")  # client_invoice | cost_entry
    alert = AIAlert(
        company_id=req.company_id,
        project_id=req.project_id,
        alert_type="agent_flag",
        severity=payload.get("severity") or "medium",
        title_tr=(payload.get("title") or "İnceleme için işaretlendi")[:200],
        body_tr=payload.get("reason") or req.description or "",
        recommended_action="Bu kaydı inceleyin.",
        source_type=source_type,
        source_id=req.target_id,
        dedup_key=f"agent_flag:{source_type}:{req.target_id}",
    )
    db.add(alert)
    db.flush()


# --- CR-012 Template A applier ------------------------------------------------
DOCS_BUCKET = "documents"


def _apply_agent_file_document(db: Session, req: ApprovalRequest) -> None:
    """Create the proposed record on approval, reusing the exact document-capture/
    confirm creation logic so VAT/total/net-due/audit stay byte-identical. The
    target project is ``req.project_id`` (the AI guess, or the project the approver
    picked when the guess was null). Cost stays the authoritative CR-007/014 input."""
    from datetime import date
    from decimal import Decimal

    from pydantic import ValidationError

    from app.responses import APIError
    from app.services.audit import record_audit, snapshot
    from app.services.calc_fields import coerce_confidence, invoice_net_due, total_with_vat, vat_amount

    payload = req.payload or {}
    destination = payload.get("destination")
    fields = dict(payload.get("fields") or {})
    if req.project_id is None:
        raise APIError(422, "VALIDATION_ERROR", "Bu öneri için bir proje seçmelisiniz")
    doc_path = payload.get("document_path")
    doc_url = f"{DOCS_BUCKET}/{doc_path}" if doc_path else None

    if destination == "cost":
        from app.models.cost_entry import CostEntry
        from app.schemas.cost import CostEntryCreate
        from app.services import fx

        try:
            rec = CostEntryCreate(
                entry_date=fields.get("entry_date") or fields.get("invoice_date"),
                cost_category=fields.get("cost_category") or "material_other",
                supplier_name=fields.get("supplier_name") or None,
                invoice_number=fields.get("invoice_number") or None,
                description=fields.get("description") or None,
                amount_try=Decimal(str(fields.get("amount_try"))),
                vat_rate=Decimal(str(fields.get("vat_rate", "20"))),
                payment_due_date=fields.get("payment_due_date") or None,
                payment_status=fields.get("payment_status") or "unpaid",
                document_url=doc_url,
                extraction_confidence=payload.get("confidence"),
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise APIError(422, "VALIDATION_ERROR", "Belge alanları geçersiz: " + str(exc)[:120])
        d = rec.model_dump()
        entry = CostEntry(
            project_id=req.project_id, company_id=req.company_id, created_by=req.requested_by,
            vat_amount_try=vat_amount(d["amount_try"], d["vat_rate"]),
            total_with_vat_try=total_with_vat(d["amount_try"], d["vat_rate"]),
            **d,
        )
        db.add(entry)
        db.flush()
        # CR-008-F: auto-link the auto-filed cost to a canonical vendor.
        from app.services.vendor_backfill import resolve_or_create_vendor_id
        entry.vendor_id = entry.vendor_id or resolve_or_create_vendor_id(
            db, req.company_id, entry.supplier_name
        )
        # CR-023.1: snapshot USD like the manual cost-create + the invoice branch
        # below — otherwise auto-filed costs save with null amount_usd. Degrades
        # gracefully, never raises.
        fx.snapshot_cost_usd(db, entry)
        record_audit(db, company_id=req.company_id, user_id=req.requested_by, table_name="cost_entries",
                     record_id=entry.id, action="INSERT", new_values=snapshot(entry))

    elif destination == "client_invoice":
        from sqlalchemy.exc import IntegrityError

        from app.models.client_invoice import ClientInvoice
        from app.schemas.invoice import ClientInvoiceCreate
        from app.services import fx

        invoice_date = fields.get("invoice_date")
        due_date = fields.get("due_date") or invoice_date
        try:
            rec = ClientInvoiceCreate(
                invoice_number=fields.get("invoice_number") or "—",
                invoice_date=invoice_date,
                hakkedis_period=fields.get("hakkedis_period") or None,
                description=fields.get("description") or None,
                amount_try=Decimal(str(fields.get("amount_try"))),
                vat_rate=Decimal(str(fields.get("vat_rate", "20"))),
                retention_amount_try=Decimal(str(fields.get("retention_amount_try", "0") or "0")),
                due_date=due_date,
                document_url=doc_url,
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise APIError(422, "VALIDATION_ERROR", "Belge alanları geçersiz: " + str(exc)[:120])
        data = rec.model_dump()
        inv = ClientInvoice(
            project_id=req.project_id, company_id=req.company_id, created_by=req.requested_by,
            vat_amount_try=vat_amount(data["amount_try"], data["vat_rate"]),
            total_with_vat_try=total_with_vat(data["amount_try"], data["vat_rate"]),
            net_due_try=invoice_net_due(data["amount_try"], data["vat_rate"], data["retention_amount_try"]),
            amount_received_try=0, payment_status="unpaid",
            extraction_confidence=coerce_confidence(payload.get("confidence")), **data,
        )
        db.add(inv)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise APIError(422, "VALIDATION_ERROR", "Bu fatura numarası zaten mevcut")
        fx.snapshot_invoice_usd(db, inv)
        record_audit(db, company_id=req.company_id, user_id=req.requested_by, table_name="client_invoices",
                     record_id=inv.id, action="INSERT", new_values=snapshot(inv))
    else:
        from app.responses import APIError as _APIError

        raise _APIError(422, "VALIDATION_ERROR", "Bilinmeyen belge hedefi")
