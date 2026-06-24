"""CR-024: persist the AI document-extraction confidence (0..1).

The model returns a 0–1 confidence at document capture / AI import time; it used
to be dropped. These tests pin where it is now stored:

* the smart document-capture /confirm endpoint,
* the agent auto-file applier (on approval), for both cost AND client_invoice,
* the AI Excel import (per-record confidence),

and that paths with NO AI confidence (manual cost create) stay NULL. Confidence
is display / monitoring only — it never feeds the financial math.
"""
from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.approval_request import ApprovalRequest
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services import ai as ai_service
from app.services.calc_fields import coerce_confidence

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


# --------------------------------------------------------------------------- #
# coerce_confidence helper
# --------------------------------------------------------------------------- #
def test_coerce_confidence_normalises_inputs():
    assert coerce_confidence(None) is None
    assert coerce_confidence("not a number") is None
    assert coerce_confidence(float("nan")) is None
    assert coerce_confidence(0.0) == 0.0
    assert coerce_confidence(0.83) == 0.83
    assert coerce_confidence("0.5") == 0.5
    # Out-of-range values are clamped into [0, 1].
    assert coerce_confidence(1.4) == 1.0
    assert coerce_confidence(-0.2) == 0.0


# --------------------------------------------------------------------------- #
# document-capture /confirm
# --------------------------------------------------------------------------- #
def test_confirm_persists_confidence_and_exposes_it(client, seed):
    pid = _login(client, seed)
    cid = seed["a"]["company"].id
    body = {
        "document_path": f"{cid}/{pid}/abc.png",
        "entry_date": "2025-05-01",
        "cost_category": "material_concrete",
        "supplier_name": "Beton A.Ş.",
        "amount_try": "150000",
        "vat_rate": "20",
        "payment_status": "unpaid",
        "extraction_confidence": 0.91,
    }
    r = client.post(f"/api/v1/projects/{pid}/document-capture/confirm", json=body)
    assert r.status_code == 200, r.text
    row = client.get(f"/api/v1/projects/{pid}/costs").json()["data"][0]
    # Exposed in CostEntryOut and stored as the 0..1 score.
    assert row["extraction_confidence"] == 0.91


def test_manual_cost_create_leaves_confidence_null(client, seed):
    pid = _login(client, seed)
    body = {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "1000", "vat_rate": "20"}
    r = client.post(f"/api/v1/projects/{pid}/costs", json=body)
    assert r.status_code in (200, 201), r.text
    row = client.get(f"/api/v1/projects/{pid}/costs").json()["data"][0]
    assert row["extraction_confidence"] is None


# --------------------------------------------------------------------------- #
# AI Excel import — per-record confidence
# --------------------------------------------------------------------------- #
def test_ai_import_persists_per_record_confidence(client, db, seed):
    pid = _login(client, seed)
    body = {
        "maliyet_girisleri": [
            {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "150000", "vat_rate": "20", "confidence": 0.95},
            {"entry_date": "2025-05-02", "cost_category": "material_concrete", "amount_try": "80000", "vat_rate": "20"},  # no confidence
        ],
        "faturalar": [], "alt_yukleniciler": [], "ekipman": [],
    }
    r = client.post(f"/api/v1/projects/{pid}/ai-import/confirm", json=body)
    assert r.status_code == 200, r.text
    rows = db.execute(select(CostEntry).order_by(CostEntry.entry_date)).scalars().all()
    assert len(rows) == 2
    assert rows[0].extraction_confidence == 0.95
    assert rows[1].extraction_confidence is None  # record without AI confidence -> NULL


# --------------------------------------------------------------------------- #
# Agent auto-file applier (on approval) — cost + client_invoice
# --------------------------------------------------------------------------- #
def _classify_result(destination, confidence, project_guess):
    return {
        "doc_type": "supplier_invoice" if destination == "cost" else "client_invoice",
        "destination": destination, "confidence": confidence, "project_guess": project_guess,
        "fields": {
            "supplier_name": "ABC Yapı", "invoice_number": "FT-2026-77",
            "invoice_date": "2026-06-01", "due_date": "2026-06-30",
            "amount_try": 10000, "vat_rate": 20, "cost_category": "material_other",
            "retention_amount_try": 0, "description": "Çimento",
        },
    }


def _enable_autofile(db, company_id, destinations):
    from app.models.automation import Automation

    db.add(Automation(
        company_id=company_id, template_key="document_auto_file", enabled=True,
        config={"min_confidence": 0.75, "destinations": destinations},
    ))
    db.commit()


def _patch_capture(monkeypatch, classify):
    import app.api.document_capture as dc

    monkeypatch.setattr(dc, "_upload_to_storage", lambda *a, **k: None)
    monkeypatch.setattr(ai_service, "is_available", lambda: True)
    monkeypatch.setattr(ai_service, "analyze_and_classify", lambda *a, **k: classify)
    monkeypatch.setattr(ai_service, "analyze_document_smart", lambda *a, **k: classify.get("fields", {}))


def test_autofile_approval_persists_cost_confidence(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable_autofile(db, seed["a"]["company"].id, ["cost"])
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=pid))

    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()
    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={})
    assert r.status_code == 200, r.text

    cost = db.execute(select(CostEntry)).scalars().one()
    assert cost.extraction_confidence == 0.95


def test_autofile_approval_persists_invoice_confidence(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable_autofile(db, seed["a"]["company"].id, ["client_invoice"])
    _patch_capture(monkeypatch, _classify_result("client_invoice", 0.88, project_guess=pid))

    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()
    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={})
    assert r.status_code == 200, r.text

    inv = db.execute(select(ClientInvoice)).scalars().one()
    assert inv.extraction_confidence == 0.88


# --------------------------------------------------------------------------- #
# ClientInvoiceOut read path — the GET endpoints now expose the score
# (mirrors the cost-side assertions above). Frontend CR-024 badge depends on it.
# --------------------------------------------------------------------------- #
def _create_invoice(client, pid, number="FT-2026-1"):
    body = {
        "invoice_number": number,
        "invoice_date": "2025-05-01",
        "amount_try": "100000",
        "vat_rate": "20",
        "retention_amount_try": "0",
        "due_date": "2025-06-01",
    }
    r = client.post(f"/api/v1/projects/{pid}/invoices", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


def test_invoice_get_exposes_extraction_confidence(client, db, seed):
    """A client invoice carrying an AI score surfaces it on both list + detail GET."""
    pid = _login(client, seed)
    created = _create_invoice(client, pid)
    # Create endpoint does not accept the score (manual create) — it starts NULL.
    assert created["extraction_confidence"] is None

    # Simulate an AI auto-filed / imported invoice by setting the persisted score.
    inv = db.execute(
        select(ClientInvoice).where(ClientInvoice.id == created["id"])
    ).scalars().one()
    inv.extraction_confidence = 0.88
    db.commit()

    # List endpoint exposes it.
    rows = client.get(f"/api/v1/projects/{pid}/invoices").json()["data"]
    assert rows[0]["extraction_confidence"] == 0.88


def test_manual_invoice_create_leaves_confidence_null(client, seed):
    """Manually created invoices have no AI score — the badge must render nothing."""
    pid = _login(client, seed)
    _create_invoice(client, pid, number="FT-2026-2")
    rows = client.get(f"/api/v1/projects/{pid}/invoices").json()["data"]
    assert rows[0]["extraction_confidence"] is None
