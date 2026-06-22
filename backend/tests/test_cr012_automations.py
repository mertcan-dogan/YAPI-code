"""CR-012 — Otomasyonlar: data model, scheduler, recurring digest, document
auto-file (§11). Backend invariants:

* the automation NEVER writes a record directly — auto-file creates only a pending
  ApprovalRequest; the CostEntry/ClientInvoice exists only after a human approves
  (the CR-011 "agent never writes directly" pattern);
* the scheduler endpoint is secret-gated, needs no user auth, and is idempotent
  (at most once per period);
* a cron run for company A never touches company B's data.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER
from app.models.approval_request import ApprovalRequest
from app.models.automation import Automation, AutomationRun
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.notification import Notification
from app.services import ai as ai_service
from app.services import automations as automations_service

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _enable(db, company_id, template_key, config, *, enabled=True, next_run_at=None, created_by=None):
    auto = Automation(
        company_id=company_id, template_key=template_key, enabled=enabled,
        config=config, next_run_at=next_run_at, created_by=created_by,
    )
    db.add(auto)
    db.commit()
    return auto


def _classify_result(destination="cost", confidence=0.95, project_guess=None):
    return {
        "doc_type": "supplier_invoice" if destination == "cost" else "client_invoice",
        "destination": destination,
        "confidence": confidence,
        "project_guess": project_guess,
        "fields": {
            "supplier_name": "ABC Yapı Malz.",
            "invoice_number": "FT-2026-77",
            "invoice_date": "2026-06-01",
            "due_date": "2026-06-30",
            "amount_try": 10000,
            "vat_rate": 20,
            "cost_category": "material_other",
            "retention_amount_try": 0,
            "description": "Çimento",
        },
    }


def _patch_capture(monkeypatch, classify):
    import app.api.document_capture as dc

    monkeypatch.setattr(dc, "_upload_to_storage", lambda *a, **k: None)
    monkeypatch.setattr(ai_service, "is_available", lambda: True)
    monkeypatch.setattr(ai_service, "analyze_and_classify", lambda *a, **k: classify)
    monkeypatch.setattr(ai_service, "analyze_document_smart", lambda *a, **k: classify.get("fields", {}))


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
def test_automation_tables_exist_and_soft_delete(db, seed):
    cid = seed["a"]["company"].id
    auto = _enable(db, cid, "recurring_digest", {"cadence": "weekly"})
    assert auto.id is not None
    assert auto.is_deleted is False
    run = AutomationRun(automation_id=auto.id, company_id=cid, template_key="recurring_digest", status="success")
    db.add(run)
    db.commit()
    assert db.execute(select(AutomationRun)).scalars().one().status == "success"


# --------------------------------------------------------------------------- #
# Scheduler endpoint (§7) — secret gating, no user auth
# --------------------------------------------------------------------------- #
def test_run_due_requires_secret(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "internal_cron_secret", "s3cret")
    # No header -> 401, no login required.
    r = client.post("/api/v1/internal/automations/run-due")
    assert r.status_code == 401
    # Wrong header -> 401.
    r = client.post("/api/v1/internal/automations/run-due", headers={"X-Internal-Secret": "nope"})
    assert r.status_code == 401
    # Correct header -> 200, runs without any user auth.
    r = client.post("/api/v1/internal/automations/run-due", headers={"X-Internal-Secret": "s3cret"})
    assert r.status_code == 200
    assert "ran" in r.json()["data"]


def test_run_due_closed_when_secret_blank(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "internal_cron_secret", "")
    r = client.post("/api/v1/internal/automations/run-due", headers={"X-Internal-Secret": ""})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Recurring digest (§6)
# --------------------------------------------------------------------------- #
def test_due_digest_composes_notifies_and_advances(db, seed):
    cid = seed["a"]["company"].id
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cfg = {"cadence": "weekly", "day_of_week": 0, "hour": 8, "tz": "Europe/Istanbul",
           "scope": "all", "delivery": {"in_app": True, "email": False}}
    auto = _enable(db, cid, "recurring_digest", cfg, next_run_at=past)

    result = automations_service.run_due_automations(db)
    assert result["ran"] == 1

    notes = db.execute(select(Notification).where(Notification.company_id == cid, Notification.notification_type == "digest")).scalars().all()
    assert len(notes) >= 1  # director (+ PM) recipients
    runs = db.execute(select(AutomationRun).where(AutomationRun.automation_id == auto.id)).scalars().all()
    assert len(runs) == 1 and runs[0].status == "success"
    assert runs[0].summary["notifications"] == len(notes)
    db.refresh(auto)
    assert auto.last_run_at is not None
    # advanced into the future (SQLite returns naive datetimes -> normalise to UTC)
    assert automations_service._as_utc(auto.next_run_at) > datetime.now(timezone.utc)


def test_digest_idempotent_within_period(db, seed):
    cid = seed["a"]["company"].id
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cfg = {"cadence": "weekly", "day_of_week": 0, "hour": 8, "tz": "Europe/Istanbul",
           "scope": "all", "delivery": {"in_app": True}}
    auto = _enable(db, cid, "recurring_digest", cfg, next_run_at=past)

    automations_service.run_due_automations(db)
    first = db.execute(select(Notification).where(Notification.notification_type == "digest")).scalars().all()

    # Simulate a duplicate/late cron tick in the SAME period.
    db.refresh(auto)
    auto.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    result = automations_service.run_due_automations(db)
    assert result["skipped"] == 1 and result["ran"] == 0

    second = db.execute(select(Notification).where(Notification.notification_type == "digest")).scalars().all()
    assert len(second) == len(first)  # no extra notifications this period


def test_digest_email_off_when_domain_unverified(db, seed, monkeypatch):
    monkeypatch.setattr(settings, "email_verified_domain", False)
    cid = seed["a"]["company"].id
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cfg = {"cadence": "weekly", "day_of_week": 0, "hour": 8, "tz": "Europe/Istanbul",
           "delivery": {"in_app": True, "email": True}}
    auto = _enable(db, cid, "recurring_digest", cfg, next_run_at=past)
    result = automations_service.run_due_automations(db)
    assert result["ran"] == 1
    run = db.execute(select(AutomationRun).where(AutomationRun.automation_id == auto.id)).scalars().one()
    assert run.status == "success"
    assert run.summary["emails"] == 0
    assert run.summary["email_skipped"] == "domain_unverified"


def test_digest_email_best_effort_never_fails_run(db, seed, monkeypatch):
    monkeypatch.setattr(settings, "email_verified_domain", True)
    # Force the email sender to blow up — the run must still succeed.
    from app.services.email_service import email_service

    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(email_service, "send_weekly_summary_email", boom)
    cid = seed["a"]["company"].id
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cfg = {"cadence": "weekly", "hour": 8, "delivery": {"in_app": True, "email": True}}
    auto = _enable(db, cid, "recurring_digest", cfg, next_run_at=past)
    result = automations_service.run_due_automations(db)
    assert result["ran"] == 1
    run = db.execute(select(AutomationRun).where(AutomationRun.automation_id == auto.id)).scalars().one()
    assert run.status == "success" and run.summary["emails"] == 0


# --------------------------------------------------------------------------- #
# Scoping (§9) — company A's run never touches company B
# --------------------------------------------------------------------------- #
def test_cron_run_is_company_scoped(db, seed):
    a, b = seed["a"]["company"].id, seed["b"]["company"].id
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    cfg = {"cadence": "weekly", "hour": 8, "delivery": {"in_app": True}}
    _enable(db, a, "recurring_digest", cfg, next_run_at=past)
    _enable(db, b, "recurring_digest", cfg, next_run_at=past)

    automations_service.run_due_automations(db)

    a_notes = db.execute(select(Notification).where(Notification.company_id == a, Notification.notification_type == "digest")).scalars().all()
    b_notes = db.execute(select(Notification).where(Notification.company_id == b, Notification.notification_type == "digest")).scalars().all()
    assert a_notes and b_notes
    a_users = {u.id for u in seed["a"]["users"].values()}
    # Every company-A digest notification is addressed to a company-A user only.
    assert all(n.user_id in a_users for n in a_notes)
    assert all(n.user_id not in a_users for n in b_notes)


# --------------------------------------------------------------------------- #
# Document auto-file (§5) — the core invariant
# --------------------------------------------------------------------------- #
def test_autofile_high_confidence_proposes_no_record_yet(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file",
            {"min_confidence": 0.75, "destinations": ["cost", "client_invoice"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=pid))

    client.login(director)
    r = client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["mode"] == "proposed"

    reqs = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().all()
    assert len(reqs) == 1
    assert reqs[0].proposed_by_agent is True
    # INVARIANT: no CostEntry created yet — the record exists only after approval.
    assert db.execute(select(CostEntry)).scalars().all() == []


def test_autofile_approve_creates_cost_with_audit(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["cost"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=pid))

    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()

    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={})
    assert r.status_code == 200, r.text
    costs = db.execute(select(CostEntry)).scalars().all()
    assert len(costs) == 1
    c = costs[0]
    assert str(c.project_id) == pid
    assert str(c.amount_try) == "10000.00"
    # VAT computed identically to the manual confirm path.
    assert str(c.total_with_vat_try) == "12000.00"
    from app.models.audit_log import AuditLog

    assert db.execute(select(AuditLog).where(AuditLog.table_name == "cost_entries", AuditLog.record_id == c.id)).scalars().all()


def test_autofile_reject_writes_nothing(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["cost"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=pid))
    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()

    r = client.put(f"/api/v1/approvals/request/{req.id}/reject", json={"reason": "yanlış"})
    assert r.status_code == 200
    assert db.execute(select(CostEntry)).scalars().all() == []
    db.refresh(req)
    assert req.status == "rejected"


def test_autofile_low_confidence_falls_back_no_proposal(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["cost"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.40))
    client.login(director)
    r = client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["mode"] == "manual" and data["fallback_reason"] == "low_confidence"
    assert db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().all() == []


def test_autofile_out_of_subset_falls_back(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.5, "destinations": ["cost"]})
    # Confident, but classified as client_invoice while only 'cost' is allowed.
    _patch_capture(monkeypatch, _classify_result("client_invoice", 0.95))
    client.login(director)
    r = client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    data = r.json()["data"]
    assert data["mode"] == "manual" and data["fallback_reason"] == "out_of_subset"
    assert db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().all() == []


def test_autofile_disabled_is_manual(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    # No automation row at all -> disabled.
    _patch_capture(monkeypatch, _classify_result("cost", 0.95))
    client.login(director)
    r = client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    data = r.json()["data"]
    assert data["mode"] == "manual" and data["automation_enabled"] is False
    assert db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().all() == []


def test_autofile_client_invoice_destination_creates_invoice_on_approve(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["client_invoice"]})
    _patch_capture(monkeypatch, _classify_result("client_invoice", 0.9, project_guess=pid))
    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("hakedis.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()
    assert req.target_table == "client_invoices"
    assert db.execute(select(ClientInvoice)).scalars().all() == []  # invariant: nothing yet

    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={})
    assert r.status_code == 200, r.text
    invs = db.execute(select(ClientInvoice)).scalars().all()
    assert len(invs) == 1 and str(invs[0].project_id) == pid


def test_autofile_requires_project_when_guess_null(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["cost"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=None))
    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()
    assert req.project_id is None

    # Approve without picking a project -> 422; nothing written.
    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={})
    assert r.status_code == 422
    assert db.execute(select(CostEntry)).scalars().all() == []

    # Approve with a chosen project -> created.
    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={"project_id": pid})
    assert r.status_code == 200, r.text
    assert len(db.execute(select(CostEntry)).scalars().all()) == 1


def test_autofile_approve_applies_field_edits(client, db, seed, monkeypatch):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    pid = str(seed["a"]["project"].id)
    _enable(db, seed["a"]["company"].id, "document_auto_file", {"min_confidence": 0.75, "destinations": ["cost"]})
    _patch_capture(monkeypatch, _classify_result("cost", 0.95, project_guess=pid))
    client.login(director)
    client.post("/api/v1/document-capture/auto-file", files={"file": ("fatura.png", PNG, "image/png")})
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.kind == "agent_file_document")).scalars().one()

    r = client.put(f"/api/v1/approvals/request/{req.id}/approve", json={"fields": {"amount_try": 5000}})
    assert r.status_code == 200, r.text
    c = db.execute(select(CostEntry)).scalars().one()
    assert str(c.amount_try) == "5000.00"


# --------------------------------------------------------------------------- #
# CRUD API (§8 backend)
# --------------------------------------------------------------------------- #
def test_automations_list_and_toggle(client, seed, db, session_factory):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    r = client.get("/api/v1/automations")
    assert r.status_code == 200
    keys = {it["template_key"] for it in r.json()["data"]}
    assert keys == {"document_auto_file", "recurring_digest"}

    r = client.put("/api/v1/automations/recurring_digest", json={
        "enabled": True,
        "config": {"cadence": "monthly", "day_of_month": 1, "hour": 9},
    })
    assert r.status_code == 200, r.text
    view = r.json()["data"]
    assert view["enabled"] is True and view["next_run_at"] is not None

    s = session_factory()
    try:
        auto = s.execute(select(Automation).where(Automation.template_key == "recurring_digest")).scalars().one()
        assert auto.enabled is True and auto.next_run_at is not None
    finally:
        s.close()


def test_automations_toggle_is_director_only(client, seed):
    pm = seed["a"]["users"][ROLE_PROJECT_MANAGER]
    client.login(pm)
    r = client.put("/api/v1/automations/recurring_digest", json={"enabled": True, "config": {}})
    assert r.status_code == 403
