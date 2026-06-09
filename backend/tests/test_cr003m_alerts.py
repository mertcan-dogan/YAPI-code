"""CR-003-M: 5 new alert types + feedback + refresh-all."""
from datetime import date, timedelta
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services.alert_engine import analyze_project


def _project(db, seed):
    return seed["a"]["project"]


def _dup_cost(db, p, uid, num="BBT-2026-001"):
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, created_by=uid, entry_date=date(2026, 1, 1),
        cost_category="other", invoice_number=num, amount_try=Decimal("10000"), vat_rate=Decimal("0"),
        vat_amount_try=Decimal("0"), total_with_vat_try=Decimal("10000"), entry_type="actual",
    ))


def test_duplicate_invoice_alert(client, seed, db):
    p = _project(db, seed)
    uid = seed["a"]["users"]["director"].id
    _dup_cost(db, p, uid)
    _dup_cost(db, p, uid)  # same supplier invoice number twice
    db.flush()
    created = analyze_project(db, p)
    assert any(c["type"] == "duplicate_invoice" for c in created)


def test_collection_risk_alert(client, seed, db):
    p = _project(db, seed)
    today = date.today()
    db.add(ClientInvoice(
        project_id=p.id, company_id=p.company_id, invoice_number="HAK-RISK", invoice_date=today - timedelta(days=80),
        amount_try=Decimal("100000"), vat_amount_try=Decimal("0"), total_with_vat_try=Decimal("100000"),
        net_due_try=Decimal("100000"), amount_received_try=Decimal("0"), payment_status="unpaid",
        due_date=today - timedelta(days=60), created_by=seed["a"]["users"]["director"].id,
    ))
    db.flush()
    created = analyze_project(db, p)
    assert any(c["type"] == "collection_risk" for c in created)


def test_unusual_cost_alert(client, seed, db):
    p = _project(db, seed)
    uid = seed["a"]["users"]["director"].id
    for amt in ("10000", "12000", "200000"):  # last is >3x the average
        db.add(CostEntry(
            project_id=p.id, company_id=p.company_id, created_by=uid, entry_date=date(2026, 3, 1),
            cost_category="equipment_rented", amount_try=Decimal(amt), vat_rate=Decimal("20"),
            vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amt), entry_type="actual",
        ))
    db.flush()
    created = analyze_project(db, p)
    assert any(c["type"] == "unusual_cost" for c in created)


def test_feedback_recorded(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    p = _project(db, seed)
    uid = seed["a"]["users"]["director"].id
    _dup_cost(db, p, uid, "DUP-FB")
    _dup_cost(db, p, uid, "DUP-FB")
    db.commit()
    analyze_project(db, p)
    alerts = client.get("/api/v1/ai/alerts").json()["data"]
    aid = alerts[0]["id"]
    r = client.put(f"/api/v1/ai/alerts/{aid}/feedback", json={"feedback": "useful"})
    assert r.status_code == 200
    assert r.json()["data"]["feedback"] == "useful"


def test_analyze_all_endpoint(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/ai/analyze-all")
    assert r.status_code == 200
    assert "alerts_created" in r.json()["data"]
