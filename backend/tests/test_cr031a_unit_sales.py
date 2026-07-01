"""CR-031-A: unit_sales register + FX-at-date + per-unit cost allocation & P&L.

No network: fx_rates are seeded; the global conftest fixture keeps live TCMB
fetch off, so rate_as_of resolves purely from the seeded cache.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.calculations.pnl import allocate_unit_costs
from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.models.unit_sale import UnitSale


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _login_dir(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])
    return seed[label]["project"].id


# --------------------------------------------------------------------------- #
# Pure allocation engine — the workbook's two dubleks fixture (+30.6% / −34.5%)
# --------------------------------------------------------------------------- #
def test_allocation_dubleks_fixture_margins_exact():
    # net m² 69.4 : 134.5; the project total IS these two units (all sold) → 203.9,
    # over a total cost of 2039 → unit costs 694 and 1345.
    units = [
        {"net_m2": "69.4", "sale_price_try": "1000", "sale_price_usd": "1000"},
        {"net_m2": "134.5", "sale_price_try": "1000", "sale_price_usd": "1000"},
    ]
    res = allocate_unit_costs(units, total_cost_try="2039", total_cost_usd="2039",
                              project_net_m2="203.9", project_gross_m2="203.9")
    assert res["basis"] == "net"
    a, b = res["allocations"]
    assert a["unit_cost_usd"] == "694.00"
    assert b["unit_cost_usd"] == "1345.00"
    assert a["margin_pct"] == "30.60"   # (1000-694)/1000
    assert b["margin_pct"] == "-34.50"  # (1000-1345)/1000


def test_allocation_net_split_sums_to_cost_when_all_units_sold():
    # Project total net m² == Σ sold (60+40+25 = 125) → the whole project is sold,
    # so Σ(per-unit cost) == the total cost.
    units = [
        {"net_m2": "60", "sale_price_try": "500000", "sale_price_usd": "10000"},
        {"net_m2": "40", "sale_price_try": "300000", "sale_price_usd": "6000"},
        {"net_m2": "25", "sale_price_try": "200000", "sale_price_usd": "4000"},
    ]
    res = allocate_unit_costs(units, total_cost_try="1000000", total_cost_usd="20000",
                              project_net_m2="125", project_gross_m2="125")
    sum_try = sum(Decimal(a["unit_cost_try"]) for a in res["allocations"])
    sum_usd = sum(Decimal(a["unit_cost_usd"]) for a in res["allocations"])
    assert sum_try == Decimal("1000000.00")  # all units sold → 100% of cost
    assert sum_usd == Decimal("20000.00")


def test_allocation_gross_fallback_when_any_net_missing():
    units = [
        {"net_m2": "60", "gross_m2": "70", "sale_price_try": "1", "sale_price_usd": "1"},
        {"net_m2": None, "gross_m2": "30", "sale_price_try": "1", "sale_price_usd": "1"},
    ]
    res = allocate_unit_costs(units, total_cost_try="100", total_cost_usd="100",
                              project_net_m2="100", project_gross_m2="100")
    assert res["basis"] == "gross"  # one unit lacks net → whole project uses gross
    assert res["allocations"][0]["unit_cost_try"] == "70.00"  # 100 × 70/100
    assert res["allocations"][1]["unit_cost_try"] == "30.00"


def test_allocation_no_project_area_is_guarded():
    # No project total m² to divide by → guarded null cost (never an exception).
    units = [{"net_m2": "100", "gross_m2": "120", "sale_price_try": "100", "sale_price_usd": "10"}]
    res = allocate_unit_costs(units, total_cost_try="100", total_cost_usd="10",
                              project_net_m2=None, project_gross_m2=None)
    assert res["allocations"][0]["unit_cost_try"] is None  # no project area → no allocation
    assert res["allocations"][0]["margin_pct"] is None


def test_allocation_no_units_empty():
    res = allocate_unit_costs([], total_cost_try="100", total_cost_usd="10",
                              project_net_m2="1000", project_gross_m2="1200")
    assert res["allocations"] == []
    assert res["totals"]["count"] == 0


def test_allocation_denominator_is_project_total_not_sold_units():
    # DGN Marti shape: ONE 146.10 m² daire sold out of a 1578 m² project (13 of 14
    # units still unsold), total cost 4,151,800.09 / $673,550.27. The unit must bear
    # only ITS m² share of the PROJECT total — NOT 100% of the cost.
    units = [{"net_m2": "146.10", "sale_price_try": "4000000", "sale_price_usd": None}]
    res = allocate_unit_costs(units, total_cost_try="4151800.09", total_cost_usd="673550.27",
                              project_net_m2="1578", project_gross_m2="2276")
    assert res["basis"] == "net"
    assert res["denom_m2"] == "1578.00"  # PROJECT total, not Σ sold (146.10)
    a = res["allocations"][0]
    assert a["unit_cost_try"] == "384396.70"           # 4,151,800.09 × 146.10/1578
    assert Decimal(a["unit_cost_try"]) < Decimal("4151800.09")  # NOT the whole cost
    assert Decimal(a["pnl_try"]) == Decimal("3615603.30")       # a profit, not a loss
    assert Decimal(a["margin_pct"]) > 0                          # positive margin
    # Σ Maliyet Payı over SOLD units < total project cost (not all units sold).
    assert Decimal(res["totals"]["cost_try"]) < Decimal("4151800.09")


# --------------------------------------------------------------------------- #
# CRUD + FX-at-date (API)
# --------------------------------------------------------------------------- #
def test_create_sale_snapshots_usd_at_sale_date(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "40.0000")
    r = client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-12", "net_m2": "120", "sale_price_try": "4000000",
        "sale_date": "2025-03-01", "buyer_name": "Ahmet Y.",
    })
    assert r.status_code == 200, r.text
    sale = db.execute(select(UnitSale).where(UnitSale.project_id == pid)).scalars().one()
    assert sale.fx_rate_usd == Decimal("40.0000")
    assert sale.sale_price_usd == Decimal("100000.00")  # 4,000,000 / 40
    assert sale.owner_side == "yuklenici"


def test_create_without_rate_leaves_usd_null(client, seed, db):
    pid = _login_dir(client, seed)  # no rate seeded
    r = client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "B-3", "net_m2": "90", "sale_price_try": "3000000", "sale_date": "2025-03-01",
    })
    assert r.status_code == 200, r.text  # save NOT blocked
    sale = db.execute(select(UnitSale).where(UnitSale.project_id == pid)).scalars().one()
    assert sale.sale_price_usd is None and sale.fx_rate_usd is None


def test_update_reprices_usd(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "40.0000")
    _seed_rate(db, "2025-06-01", "30.0000")
    sid = client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "C-1", "net_m2": "100", "sale_price_try": "4000000", "sale_date": "2025-03-01",
    }).json()["data"]["id"]
    r = client.put(f"/api/v1/projects/{pid}/unit-sales/{sid}", json={"sale_date": "2025-06-01"})
    assert r.status_code == 200, r.text
    db.expire_all()
    sale = db.get(UnitSale, sid)
    assert sale.fx_rate_usd == Decimal("30.0000")
    assert sale.sale_price_usd == Decimal("133333.33")  # 4,000,000 / 30


def test_delete_is_soft(client, seed, db):
    pid = _login_dir(client, seed)
    sid = client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "D-9", "net_m2": "80", "sale_price_try": "2500000", "sale_date": "2025-03-01",
    }).json()["data"]["id"]
    r = client.delete(f"/api/v1/projects/{pid}/unit-sales/{sid}")
    assert r.status_code == 200, r.text
    sale = db.get(UnitSale, sid)
    assert sale.is_deleted is True
    # excluded from the list
    rows = client.get(f"/api/v1/projects/{pid}/unit-sales").json()["data"]["allocations"]
    assert rows == []


# --------------------------------------------------------------------------- #
# Per-unit allocation over the real rollup (API end-to-end)
# --------------------------------------------------------------------------- #
def test_endpoint_allocation_sums_to_cost(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "40.0000")
    # Project total net m² == Σ sold (60+40 = 100): the whole project is sold.
    p = seed["a"]["project"]
    p.construction_net_m2 = Decimal("100")
    db.add(p)
    db.commit()
    # One authoritative cost: 400,000 TRY → 10,000 USD snapshot.
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0",
    })
    for label, net in (("A", "60"), ("B", "40")):
        client.post(f"/api/v1/projects/{pid}/unit-sales", json={
            "unit_label": label, "net_m2": net, "sale_price_try": "5000000", "sale_date": "2025-03-01",
        })
    data = client.get(f"/api/v1/projects/{pid}/unit-sales").json()["data"]
    assert data["basis"] == "net"
    assert data["denom_m2"] == "100.00"  # PROJECT total net m²
    assert data["cost_total_try"] == "400000.00"
    assert data["cost_total_usd"] == "10000.00"
    a, b = data["allocations"]
    assert a["unit_cost_try"] == "240000.00" and b["unit_cost_try"] == "160000.00"
    assert a["unit_cost_usd"] == "6000.00" and b["unit_cost_usd"] == "4000.00"


def test_endpoint_allocation_uses_project_total_when_not_all_sold(client, seed, db):
    # Regression for the live DGN Marti bug: ONE 100 m² unit sold out of a 1000 m²
    # project (rest unsold). The unit bears 10% of cost via the PROJECT total — not
    # 100% — so a real sale shows a profit, not a phantom whole-project loss.
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "40.0000")
    p = seed["a"]["project"]
    p.construction_net_m2 = Decimal("1000")  # 1000 m² project; only 100 m² sold
    db.add(p)
    db.commit()
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0",
    })
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "13", "net_m2": "100", "sale_price_try": "1000000", "sale_date": "2025-03-01",
    })
    data = client.get(f"/api/v1/projects/{pid}/unit-sales").json()["data"]
    assert data["basis"] == "net"
    assert data["denom_m2"] == "1000.00"               # PROJECT total, NOT 100 (sold)
    a = data["allocations"][0]
    assert a["unit_cost_try"] == "40000.00"            # 400,000 × 100/1000 — NOT 400,000
    assert a["unit_cost_usd"] == "1000.00"             # 10,000 × 100/1000
    assert Decimal(a["pnl_try"]) == Decimal("960000.00")  # 1,000,000 − 40,000 → profit
    assert a["margin_pct"] == "96.00"                  # positive margin, not a loss
    # Σ Maliyet Payı over SOLD units is a proper subset of the project cost.
    assert Decimal(data["totals"]["cost_try"]) < Decimal("400000")


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
def test_company_b_cannot_read_company_a_sales(client, seed, db):
    pid_a = _login_dir(client, seed, "a")
    client.post(f"/api/v1/projects/{pid_a}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "1000000", "sale_date": "2025-03-01",
    })
    # Company B director cannot see project A at all (404, existence not leaked).
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{pid_a}/unit-sales")
    assert r.status_code == 404
