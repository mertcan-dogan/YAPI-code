"""CR-004-N: approval workflow extended to all triggers."""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER
from app.models.budget_line_item import BudgetLineItem
from app.models.cost_entry import CostEntry
from app.models.subcontractor import Subcontractor
from app.models.variation import Variation


def _enable(db, company, **flags):
    for k, v in flags.items():
        setattr(company, k, v)
    db.commit()


def _pending(client):
    r = client.get("/api/v1/approvals")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_budget_change_requires_approval_then_applies(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_budget_approval=True)
    client.login(a["users"][ROLE_DIRECTOR])

    r = client.put(
        f"/api/v1/projects/{a['project'].id}/budget/material_concrete",
        json={"original_budget_try": "250000", "approved_variations_try": "0"},
    )
    assert r.status_code == 200 and r.json()["data"]["pending_approval"] is True

    pend = [p for p in _pending(client) if p["kind"] == "budget_change"]
    assert len(pend) == 1
    req_id = pend[0]["request_id"]

    # Not applied yet.
    line = db.execute(
        BudgetLineItem.__table__.select().where(BudgetLineItem.cost_category == "material_concrete")
    ).first()
    assert line is None or Decimal(str(line.original_budget_try)) != Decimal("250000")

    assert client.put(f"/api/v1/approvals/request/{req_id}/approve").status_code == 200
    db.expire_all()
    line = db.execute(
        BudgetLineItem.__table__.select().where(BudgetLineItem.cost_category == "material_concrete")
    ).first()
    assert Decimal(str(line.original_budget_try)) == Decimal("250000")


def test_cost_deletion_requires_approval(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_deletion_approval=True)
    cost = CostEntry(
        project_id=a["project"].id, company_id=a["company"].id, created_by=a["users"][ROLE_DIRECTOR].id,
        entry_date=date(2026, 6, 1), cost_category="materials", amount_try=Decimal("1000"),
        total_with_vat_try=Decimal("1200"),
    )
    db.add(cost)
    db.commit()
    cid = cost.id

    client.login(a["users"][ROLE_DIRECTOR])
    r = client.delete(f"/api/v1/projects/{a['project'].id}/costs/{cid}")
    assert r.status_code == 200 and r.json()["data"]["pending_approval"] is True

    db.expire_all()
    assert db.get(CostEntry, cid).is_deleted is False  # not deleted yet

    req_id = [p for p in _pending(client) if p["kind"] == "cost_deletion"][0]["request_id"]
    assert client.put(f"/api/v1/approvals/request/{req_id}/approve").status_code == 200
    db.expire_all()
    assert db.get(CostEntry, cid).is_deleted is True


def test_subcontractor_change_requires_approval(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_subcontractor_approval=True)
    sub = Subcontractor(
        project_id=a["project"].id, company_id=a["company"].id, name="Alt A",
        contract_value_try=Decimal("100000"),
    )
    db.add(sub)
    db.commit()
    sid = sub.id

    client.login(a["users"][ROLE_DIRECTOR])
    r = client.put(
        f"/api/v1/projects/{a['project'].id}/subcontractors/{sid}",
        json={"contract_value_try": "150000"},
    )
    assert r.status_code == 200 and r.json()["data"]["pending_approval"] is True
    db.expire_all()
    assert db.get(Subcontractor, sid).contract_value_try == Decimal("100000")

    req_id = [p for p in _pending(client) if p["kind"] == "subcontractor_change"][0]["request_id"]
    assert client.put(f"/api/v1/approvals/request/{req_id}/approve").status_code == 200
    db.expire_all()
    assert db.get(Subcontractor, sid).contract_value_try == Decimal("150000")


def test_variation_approval_requires_approval(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_variation_approval=True)
    v = Variation(
        project_id=a["project"].id, company_id=a["company"].id, created_by=a["users"][ROLE_DIRECTOR].id,
        variation_number="EK-1", title="Ek iş", submitted_date=date(2026, 6, 1),
        value_try=Decimal("50000"), cost_category="materials", status="pending",
    )
    db.add(v)
    db.commit()
    vid = v.id

    client.login(a["users"][ROLE_DIRECTOR])
    r = client.put(
        f"/api/v1/projects/{a['project'].id}/variations/{vid}",
        json={"status": "approved", "approved_value_try": "50000"},
    )
    assert r.status_code == 200 and r.json()["data"]["pending_approval"] is True
    db.expire_all()
    assert db.get(Variation, vid).status == "pending"  # not approved yet

    req_id = [p for p in _pending(client) if p["kind"] == "variation_approval"][0]["request_id"]
    assert client.put(f"/api/v1/approvals/request/{req_id}/approve").status_code == 200
    db.expire_all()
    assert db.get(Variation, vid).status == "approved"


def test_reject_request_discards_change(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_budget_approval=True)
    client.login(a["users"][ROLE_DIRECTOR])
    client.put(
        f"/api/v1/projects/{a['project'].id}/budget/labour_direct",
        json={"original_budget_try": "999000", "approved_variations_try": "0"},
    )
    req_id = [p for p in _pending(client) if p["kind"] == "budget_change"][0]["request_id"]
    r = client.put(f"/api/v1/approvals/request/{req_id}/reject", json={"reason": "Gereksiz"})
    assert r.status_code == 200
    assert not [p for p in _pending(client) if p["kind"] == "budget_change"]


def test_settings_expose_all_toggles(client, db, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/settings/company")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    for key in (
        "require_budget_approval", "require_subcontractor_approval",
        "require_deletion_approval", "require_variation_approval",
        "cost_approval_threshold_try",
    ):
        assert key in data

    upd = client.put("/api/v1/settings/company", json={"require_deletion_approval": True, "cost_approval_threshold_try": 750000})
    assert upd.status_code == 200
    assert upd.json()["data"]["require_deletion_approval"] is True
    assert float(upd.json()["data"]["cost_approval_threshold_try"]) == 750000


def test_non_director_cannot_decide(client, db, seed):
    a = seed["a"]
    _enable(db, a["company"], require_budget_approval=True)
    client.login(a["users"][ROLE_DIRECTOR])
    client.put(
        f"/api/v1/projects/{a['project'].id}/budget/site_overhead",
        json={"original_budget_try": "10000", "approved_variations_try": "0"},
    )
    req_id = [p for p in _pending(client) if p["kind"] == "budget_change"][0]["request_id"]

    client.login(a["users"][ROLE_PROJECT_MANAGER])
    assert client.put(f"/api/v1/approvals/request/{req_id}/approve").status_code == 403
