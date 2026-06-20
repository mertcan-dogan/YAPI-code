"""CR-031-F: consolidated coverage for the sell-side lane (§6).

Fills the cross-cutting gaps left by A–E: FX walk-back on the new income rows,
cross-company modify isolation + forged company_id, and a full sell-side
end-to-end payload-consistency check. No network: fx_rates seeded; conftest keeps
live TCMB fetch off.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.models.landowner_payment import LandownerPayment
from app.models.unit_sale import UnitSale


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _login_dir(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])
    return seed[label]["project"].id


def _set_model(db, seed, model, label="a", **extra):
    p = seed[label]["project"]
    p.revenue_model = model
    for k, v in extra.items():
        setattr(p, k, v)
    db.add(p)
    db.commit()
    return p


# --------------------------------------------------------------------------- #
# FX-at-date walk-back (CR-014) applies to the new income rows
# --------------------------------------------------------------------------- #
def test_sale_fx_walks_back_to_business_day(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-07", "31.5000")   # Friday
    assert date(2025, 3, 9).weekday() == 6     # the sale falls on a Sunday
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "WB-1", "net_m2": "100", "sale_price_try": "3150000", "sale_date": "2025-03-09"})
    sale = db.execute(select(UnitSale).where(UnitSale.project_id == pid)).scalars().one()
    assert sale.fx_rate_usd == Decimal("31.5000")          # walked back to Friday
    assert sale.sale_price_usd == Decimal("100000.00")     # 3,150,000 / 31.5


def test_landowner_fx_walks_back_to_business_day(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-07", "31.5000")   # Friday
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-03-09", "amount_try": "6300000"})   # Sunday
    p = db.execute(select(LandownerPayment).where(LandownerPayment.project_id == pid)).scalars().one()
    assert p.fx_rate_usd == Decimal("31.5000")
    assert p.amount_usd == Decimal("200000.00")            # 6,300,000 / 31.5


# --------------------------------------------------------------------------- #
# Isolation: cross-company READ + MODIFY blocked; forged company_id ignored
# --------------------------------------------------------------------------- #
def test_company_b_cannot_modify_company_a_sale(client, seed, db):
    pid_a = _login_dir(client, seed, "a")
    sid = client.post(f"/api/v1/projects/{pid_a}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "1000000", "sale_date": "2025-03-01"}).json()["data"]["id"]
    # Company B cannot update or delete it (project scoping → 404, existence hidden).
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.put(f"/api/v1/projects/{pid_a}/unit-sales/{sid}", json={"sale_price_try": "1"}).status_code == 404
    assert client.delete(f"/api/v1/projects/{pid_a}/unit-sales/{sid}").status_code == 404
    # The row is untouched.
    db.expire_all()
    assert db.get(UnitSale, sid).sale_price_try == Decimal("1000000.00")


def test_company_b_cannot_modify_company_a_landowner(client, seed, db):
    pid_a = _login_dir(client, seed, "a")
    pmid = client.post(f"/api/v1/projects/{pid_a}/landowner-payments", json={
        "payment_date": "2025-03-01", "amount_try": "1000000"}).json()["data"]["id"]
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.put(f"/api/v1/projects/{pid_a}/landowner-payments/{pmid}", json={"amount_try": "1"}).status_code == 404
    assert client.delete(f"/api/v1/projects/{pid_a}/landowner-payments/{pmid}").status_code == 404


def test_forged_company_id_in_body_is_ignored(client, seed, db):
    pid_a = _login_dir(client, seed, "a")
    company_b_id = str(seed["b"]["company"].id)
    # A director POSTs with a forged company_id of company B in the body.
    sid = client.post(f"/api/v1/projects/{pid_a}/unit-sales", json={
        "unit_label": "FORGE", "net_m2": "100", "sale_price_try": "1000000",
        "sale_date": "2025-03-01", "company_id": company_b_id}).json()["data"]["id"]
    sale = db.get(UnitSale, sid)
    # The company_id is taken from the authenticated user, NOT the forged body field.
    assert str(sale.company_id) == str(seed["a"]["company"].id)
    assert str(sale.company_id) != company_b_id


# --------------------------------------------------------------------------- #
# End-to-end: the dashboard payload is internally consistent for a sell-side project
# --------------------------------------------------------------------------- #
def test_sell_side_dashboard_payload_is_consistent(client, seed, db):
    pid = _login_dir(client, seed)
    _set_model(db, seed, "kat_karsiligi", construction_net_m2=Decimal("500"),
               contractor_share_pct=Decimal("60.00"), unit_count=4)
    _seed_rate(db, "2025-03-01", "40.0000")
    _seed_rate(db, "2025-09-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "5000000", "sale_date": "2025-09-01"})
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-09-01", "amount_try": "2000000"})

    dash = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]
    pnl = dash["pnl"]
    ir = dash["investment_return"]
    sales = client.get(f"/api/v1/projects/{pid}/unit-sales").json()["data"]
    ledger = client.get(f"/api/v1/projects/{pid}/landowner-payments").json()["data"]

    # Revenue is sell-side and equals Σ sales + Σ landowner (no double count).
    assert pnl["revenue_source"] == "sales"
    assert pnl["revenue_try"] == "7000000.00"   # 5,000,000 + 2,000,000
    assert pnl["revenue_breakdown"]["unit_sales_try"] == sales["totals"]["sale_price_try"]
    assert pnl["revenue_breakdown"]["landowner_try"] == ledger["rollup"]["total_try"]
    # Net (excl financing) = revenue − cost; ROI present.
    assert pnl["net_excl_financing_try"] == "6600000.00"   # 7,000,000 − 400,000
    assert ir["roi_pct"] is not None and ir["revenue_source"] == "sales"
    # Contractor split allocates cost by the project share %.
    assert pnl["split"]["contractor"]["allocated_cost_try"] == "240000.00"   # 400,000 × 60%
