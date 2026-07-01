"""CR-014-C: USD aggregates = SUM of per-row amount_usd snapshots (§0.2).

The whole point: a USD total adds up the point-in-time per-row snapshots, so it
does NOT equal total_try / a single today's rate when rows carry different rates.
Missing snapshots are counted so a total never looks complete when it isn't.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services import financials as fin


def _cost(db, proj, cid, uid, amount_try, amount_usd=None, fx=None,
          pending=False, deleted=False, entry_date=date(2025, 1, 1)):
    c = CostEntry(
        project_id=proj.id, company_id=cid, created_by=uid, entry_date=entry_date,
        cost_category="other", amount_try=Decimal(amount_try),
        vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amount_try),
        amount_usd=(Decimal(amount_usd) if amount_usd is not None else None),
        fx_rate_usd=(Decimal(fx) if fx is not None else None),
        pending_approval=pending, is_deleted=deleted, payment_status="unpaid",
    )
    db.add(c)
    db.flush()
    return c


def _invoice(db, proj, cid, uid, number, amount_try, amount_usd=None, fx=None):
    inv = ClientInvoice(
        project_id=proj.id, company_id=cid, created_by=uid, invoice_number=number,
        invoice_date=date(2025, 1, 1), amount_try=Decimal(amount_try),
        vat_amount_try=Decimal("0"), total_with_vat_try=Decimal(amount_try),
        net_due_try=Decimal(amount_try), due_date=date(2025, 2, 1),
        amount_received_try=Decimal("0"), payment_status="unpaid",
        amount_usd=(Decimal(amount_usd) if amount_usd is not None else None),
        fx_rate_usd=(Decimal(fx) if fx is not None else None),
    )
    db.add(inv)
    db.flush()
    return inv


# --------------------------------------------------------------------------- #
# Core: snapshot sum, NOT total_try / today's rate
# --------------------------------------------------------------------------- #
def test_usd_total_is_sum_of_snapshots_not_naive_division(db, seed):
    a = seed["a"]
    p, cid, uid = a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id
    # Two rows valued at DIFFERENT rates: 10000@20 -> 500, 10000@40 -> 250.
    _cost(db, p, cid, uid, "10000", amount_usd="500.00", fx="20.0000")
    _cost(db, p, cid, uid, "10000", amount_usd="250.00", fx="40.0000")
    db.commit()

    agg = fin.project_usd_totals(db, p)
    assert agg["costs"]["amount_usd"] == "750.00"  # 500 + 250 (snapshot sum)

    # A naive total_try / single-rate conversion would give a DIFFERENT number.
    total_try = db.execute(
        select(func.sum(CostEntry.amount_try)).where(CostEntry.project_id == p.id)
    ).scalar_one()
    naive_today = str((Decimal(str(total_try)) / Decimal("40.0000")).quantize(Decimal("0.01")))
    assert naive_today == "500.00"
    assert agg["costs"]["amount_usd"] != naive_today  # 750.00 != 500.00 — the point

    # TRY total is unchanged by any of this.
    assert Decimal(str(total_try)) == Decimal("20000")


def test_usd_missing_count_reflects_null_snapshots(db, seed):
    a = seed["a"]
    p, cid, uid = a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id
    _cost(db, p, cid, uid, "10000", amount_usd="500.00", fx="20.0000")
    _cost(db, p, cid, uid, "9999", amount_usd=None, fx=None)   # pre-history / no rate
    db.commit()

    agg = fin.project_usd_totals(db, p)
    assert agg["costs"]["amount_usd"] == "500.00"      # null row ignored by the sum
    assert agg["costs"]["usd_missing_count"] == 1      # ...but surfaced honestly


def test_invoice_usd_aggregate(db, seed):
    a = seed["a"]
    p, cid, uid = a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id
    _invoice(db, p, cid, uid, "HAK-1", "30000", amount_usd="1000.00", fx="30.0000")
    _invoice(db, p, cid, uid, "HAK-2", "40000", amount_usd="1000.00", fx="40.0000")
    _invoice(db, p, cid, uid, "HAK-3", "5000", amount_usd=None, fx=None)
    db.commit()

    agg = fin.project_usd_totals(db, p)
    assert agg["invoices"]["amount_usd"] == "2000.00"
    assert agg["invoices"]["usd_missing_count"] == 1


def test_aggregate_excludes_pending_and_deleted_costs(db, seed):
    a = seed["a"]
    p, cid, uid = a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id
    _cost(db, p, cid, uid, "10000", amount_usd="500.00", fx="20.0000")
    _cost(db, p, cid, uid, "10000", amount_usd="999.00", fx="20.0000", pending=True)
    _cost(db, p, cid, uid, "10000", amount_usd="888.00", fx="20.0000", deleted=True)
    db.commit()

    agg = fin.project_usd_totals(db, p)
    assert agg["costs"]["amount_usd"] == "500.00"      # pending + deleted excluded
    assert agg["costs"]["usd_missing_count"] == 0


def test_company_aggregate_scoped_by_project_ids(db, seed):
    a, b = seed["a"], seed["b"]
    _cost(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "10000", amount_usd="500.00", fx="20.0000")
    _cost(db, b["project"], b["company"].id, b["users"][ROLE_DIRECTOR].id, "10000", amount_usd="700.00", fx="20.0000")
    db.commit()

    only_a = fin.usd_aggregates(db, project_ids=[a["project"].id])
    assert only_a["costs"]["amount_usd"] == "500.00"  # company B excluded


# --------------------------------------------------------------------------- #
# API wiring
# --------------------------------------------------------------------------- #
def test_project_dashboard_returns_usd(client, db, seed):
    a = seed["a"]
    _cost(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "10000", amount_usd="500.00", fx="20.0000")
    db.commit()
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{a['project'].id}/dashboard")
    assert r.status_code == 200, r.text
    usd = r.json()["data"]["usd"]
    assert usd["costs"]["amount_usd"] == "500.00"
    assert usd["costs"]["usd_missing_count"] == 0
    # TRY financials are still present and unchanged.
    assert "financials" in r.json()["data"]


def test_company_dashboard_returns_usd(client, db, seed):
    a = seed["a"]
    _cost(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "10000", amount_usd="500.00", fx="20.0000")
    _invoice(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "HAK-C1", "30000", amount_usd="1000.00", fx="30.0000")
    db.commit()
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    usd = r.json()["data"]["usd"]
    assert usd["costs"]["amount_usd"] == "500.00"
    assert usd["invoices"]["amount_usd"] == "1000.00"


def test_cashflow_exposes_usd_meta(client, db, seed):
    a = seed["a"]
    _cost(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "10000", amount_usd="500.00", fx="20.0000")
    db.commit()
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{a['project'].id}/cashflow")
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["usd"]["costs"]["amount_usd"] == "500.00"


def test_invoice_list_exposes_usd_fields(client, db, seed):
    a = seed["a"]
    _invoice(db, a["project"], a["company"].id, a["users"][ROLE_DIRECTOR].id, "HAK-OUT", "30000", amount_usd="1000.00", fx="30.0000")
    db.commit()
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{a['project'].id}/invoices")
    assert r.status_code == 200, r.text
    row = r.json()["data"][0]
    assert row["amount_usd"] == "1000.00"
    assert row["fx_rate_usd"] == "30.0000"
