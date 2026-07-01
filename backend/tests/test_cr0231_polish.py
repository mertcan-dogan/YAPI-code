"""CR-023.1: committed-cost display polish + document-capture USD snapshot.

- Budget "Taahhüt" total = exposure (actual + open committed), NOT legacy gross
  (the proven case: commit 100k + 60k linked invoice → 100k, not 160k).
- portfolio_performance carries per-project open committed for the chart.
- Costs created via document-capture /confirm, smart-capture /confirm, and the
  auto-file approval get a non-null amount_usd when a rate is resolvable.

No network: fx_rates seeded; the conftest fixture keeps live TCMB fetch off.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate


def _login(client, seed, co="a"):
    client.login(seed[co]["users"][ROLE_DIRECTOR])
    return seed[co]["project"].id


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _mk_commitment(client, pid, amount="100000", cat="material_steel", **extra):
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-02-01", "entry_type": "committed", "cost_category": cat,
        "amount_try": amount, "vat_rate": "20", **extra,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


# --------------------------------------------------------------------------- #
# Fix 1 — budget "Taahhüt" total = exposure, not gross (no double-count on display)
# --------------------------------------------------------------------------- #
def test_budget_taahhut_total_is_exposure_not_gross(client, seed):
    pid = _login(client, seed)
    commit = _mk_commitment(client, pid, "100000")
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "60000", "vat_rate": "20", "commitment_id": commit["id"],
    })
    assert r.status_code == 200, r.text

    totals = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]["totals"]
    # The displayed "Taahhüt" figure (exposure) = Faturalanan 60k + Açık 40k = 100k.
    assert totals["exposure_try"] == "100000.00"
    assert totals["invoiced_try"] == "60000.00"
    assert totals["open_committed_try"] == "40000.00"
    # Reconciles exactly: exposure == invoiced + open.
    assert Decimal(totals["exposure_try"]) == Decimal(totals["invoiced_try"]) + Decimal(totals["open_committed_try"])
    # Legacy gross stays in the payload (reports/agent_tools) — and is the 160k we
    # must NOT show.
    assert totals["committed_try"] == "160000.00"


# --------------------------------------------------------------------------- #
# Fix 3 — portfolio_performance carries per-project open committed for the chart
# --------------------------------------------------------------------------- #
def test_portfolio_performance_has_open_committed(client, seed):
    pid = _login(client, seed)
    commit = _mk_commitment(client, pid, "100000")
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "60000", "vat_rate": "20", "commitment_id": commit["id"],
    })
    perf = client.get("/api/v1/dashboard").json()["data"]["portfolio_performance"]
    row = next(p for p in perf if p["project"] == seed["a"]["project"].name)
    assert "committed_try" in row
    assert row["committed_try"] == "40000.00"  # open committed (100k − 60k linked)


# --------------------------------------------------------------------------- #
# Fix 4 — captured / auto-filed costs get a non-null USD snapshot
# --------------------------------------------------------------------------- #
def test_document_capture_confirm_snapshots_usd(client, seed, db):
    pid = _login(client, seed)
    cid = seed["a"]["company"].id
    _seed_rate(db, "2025-05-01", "32.0000")
    body = {
        "document_path": f"{cid}/{pid}/abc.png",
        "entry_date": "2025-05-01",
        "cost_category": "material_concrete",
        "supplier_name": "Beton A.Ş.",
        "amount_try": "150000",
        "vat_rate": "20",
        "payment_status": "unpaid",
    }
    r = client.post(f"/api/v1/projects/{pid}/document-capture/confirm", json=body)
    assert r.status_code == 200, r.text
    entry = db.execute(select(CostEntry).where(CostEntry.id == uuid.UUID(r.json()["data"]["id"]))).scalar_one()
    assert entry.amount_usd is not None
    assert entry.amount_usd == Decimal("150000") / Decimal("32.0000")  # ex-VAT / rate, rounded
    assert entry.fx_rate_usd == Decimal("32.0000")


def test_smart_capture_confirm_snapshots_usd(client, seed, db):
    pid = _login(client, seed)
    cid = seed["a"]["company"].id
    _seed_rate(db, "2025-05-01", "30.0000")
    body = {
        "project_id": str(pid),
        "document_path": f"{cid}/inbox/def.png",
        "file_sha256": "a" * 64,
        "entry_date": "2025-05-01",
        "cost_category": "material_concrete",
        "supplier_name": "Beton A.Ş.",
        "amount_try": "90000",
        "vat_rate": "20",
        "payment_status": "unpaid",
    }
    r = client.post("/api/v1/document-capture/confirm", json=body)
    assert r.status_code == 200, r.text
    entry = db.execute(select(CostEntry).where(CostEntry.id == uuid.UUID(r.json()["data"]["id"]))).scalar_one()
    assert entry.amount_usd is not None
    assert entry.fx_rate_usd == Decimal("30.0000")


def test_autofile_approval_snapshots_usd(client, seed, db):
    # The auto-file approval path (_apply_agent_file_document, cost branch) must
    # snapshot USD just like the manual capture + the invoice branch.
    from app.models.approval_request import ApprovalRequest
    from app.services import approvals as approvals_service

    company = seed["a"]["company"]
    project = seed["a"]["project"]
    director = seed["a"]["users"][ROLE_DIRECTOR]
    _seed_rate(db, "2025-05-01", "25.0000")

    req = ApprovalRequest(
        company_id=company.id, project_id=project.id, kind="agent_file_document",
        target_table="cost_entries", proposed_by_agent=True, requested_by=director.id,
        payload={
            "destination": "cost",
            "document_path": f"{project.id}/auto.png",
            "fields": {
                "entry_date": "2025-05-01", "cost_category": "material_concrete",
                "supplier_name": "Mersin Beton", "amount_try": "200000", "vat_rate": "20",
            },
        },
    )
    db.add(req)
    db.flush()
    approvals_service.apply_request(db, req)
    db.commit()

    entry = db.execute(
        select(CostEntry).where(CostEntry.project_id == project.id, CostEntry.supplier_name == "Mersin Beton")
    ).scalar_one()
    assert entry.amount_usd is not None
    assert entry.fx_rate_usd == Decimal("25.0000")
