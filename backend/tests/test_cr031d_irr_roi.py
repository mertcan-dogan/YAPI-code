"""CR-031-D: IRR (XIRR over irregular dates) / ROI / duration.

The XIRR fixture cross-checks against Excel's XIRR (Actual/365 basis). No network:
fx_rates seeded; conftest keeps live TCMB fetch off.
"""
from datetime import date
from decimal import Decimal

from app.calculations.pnl import investment_return as calc_ir
from app.calculations.pnl import xirr, yearly_cashflow_rows
from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.services import sales as sales_service


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
# Pure XIRR — reference fixture (Excel XIRR ≈ 0.373362535)
# --------------------------------------------------------------------------- #
def test_xirr_matches_excel_reference():
    flows = [
        (date(2008, 1, 1), -10000),
        (date(2008, 3, 1), 2750),
        (date(2008, 10, 30), 4250),
        (date(2009, 2, 15), 3250),
        (date(2009, 4, 1), 2750),
    ]
    r = xirr(flows)
    assert r is not None
    assert abs(r - 0.373362535) < 1e-4  # within tolerance of the reference XIRR


def test_xirr_simple_one_year_is_ten_pct():
    # 365-day gap, +10% return → exactly 0.10.
    r = xirr([(date(2021, 1, 1), -1000), (date(2022, 1, 1), 1100)])
    assert abs(r - 0.10) < 1e-6


def test_xirr_degenerate_series_return_none_no_throw():
    assert xirr([(date(2021, 1, 1), 100), (date(2022, 1, 1), 200)]) is None   # all positive
    assert xirr([(date(2021, 1, 1), -100), (date(2022, 1, 1), -200)]) is None  # all negative
    assert xirr([(date(2021, 1, 1), -100)]) is None                            # single flow
    assert xirr([]) is None                                                    # empty


# --------------------------------------------------------------------------- #
# Pure investment_return — ROI / duration / per-m² exact
# --------------------------------------------------------------------------- #
def test_calc_roi_and_duration_exact():
    flows = [(date(2025, 3, 1), -400000), (date(2025, 9, 1), 1000000)]
    out = calc_ir(flows, flows, revenue_try="1000000", cost_try="400000",
                  start_date=date(2025, 1, 1), last_date=date(2025, 9, 1),
                  net_m2="500", unit_count=10)
    assert out["roi_pct"] == "150.00"            # (1,000,000 - 400,000) / 400,000
    assert out["net_profit_try"] == "600000.00"
    assert out["duration_months"] == 8           # Jan → Sep
    assert out["profit_per_net_m2_try"] == "1200.00"  # 600,000 / 500
    assert out["profit_per_unit_try"] == "60000.00"   # 600,000 / 10
    assert out["irr_try_pct"] is not None        # both signs → a real IRR


def test_calc_roi_zero_cost_guarded():
    out = calc_ir([], [], revenue_try="100", cost_try="0", start_date=None, last_date=None)
    assert out["roi_pct"] is None
    assert out["irr_try_pct"] is None  # empty series


def test_yearly_rows_split_in_out():
    rows = yearly_cashflow_rows(
        [(date(2024, 5, 1), -400000), (date(2025, 9, 1), 1000000)],
        [(date(2024, 5, 1), -10000), (date(2025, 9, 1), 25000)],
    )
    assert [r["year"] for r in rows] == [2024, 2025]
    assert rows[0]["outflow_try"] == "400000.00" and rows[0]["net_try"] == "-400000.00"
    assert rows[1]["inflow_try"] == "1000000.00" and rows[1]["net_usd"] == "25000.00"


# --------------------------------------------------------------------------- #
# Service — over the real lanes + payload
# --------------------------------------------------------------------------- #
def test_investment_return_over_real_lanes(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "kat_karsiligi", construction_net_m2=Decimal("500"))
    _seed_rate(db, "2025-03-01", "40.0000")
    _seed_rate(db, "2025-09-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "1000000", "sale_date": "2025-09-01"})

    block = sales_service.investment_return(db, p)
    assert block["revenue_source"] == "sales"
    assert block["roi_pct"] == "150.00"          # (1,000,000 - 400,000) / 400,000
    assert block["duration_months"] == 8          # 2025-01 → 2025-09
    assert block["irr_try_pct"] is not None and float(block["irr_try_pct"]) > 0
    assert block["irr_usd_pct"] is not None       # USD snapshots present
    assert len(block["yearly"]) == 1 and block["yearly"][0]["year"] == 2025


def test_investment_return_degenerate_no_inflow(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "yap_sat")
    _seed_rate(db, "2025-03-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})
    # No inflow → all-negative series → IRR null, but no exception and ROI computes.
    block = sales_service.investment_return(db, p)
    assert block["irr_try_pct"] is None
    assert block["roi_pct"] is not None


def test_dashboard_payload_includes_investment_return(client, seed, db):
    pid = _login_dir(client, seed)
    _set_model(db, seed, "kat_karsiligi")
    r = client.get(f"/api/v1/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    ir = r.json()["data"]["investment_return"]
    assert "irr_try_pct" in ir and "roi_pct" in ir and "yearly" in ir
