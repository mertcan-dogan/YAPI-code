"""CR-015-B: compute_financing_cost + separable forecast exposure.

Cashflow is monkeypatched to a known set of (net, cumulative) months so the
accrual math is exact and deterministic; fx_rates are seeded (no network — the
global conftest fixture keeps live TCMB fetch off). The critical invariant —
financing NEVER touches actuals — is asserted on vs off.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate
from app.services import financials, financing


def _row(month_key: str, net: str, cum: str) -> dict:
    y, m = (int(x) for x in month_key.split("-"))
    return {"month": month_key, "year": y, "month_num": m,
            "net_try": Decimal(net), "cumulative_try": Decimal(cum)}


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _enable(db, company, rate="12", basis="cumulative"):
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal(rate)
    company.financing_basis = basis
    db.commit()


def _patch_cashflow(monkeypatch, rows):
    monkeypatch.setattr(financials, "project_cashflow", lambda db, project, today=None: rows)


# --------------------------------------------------------------------------- #
# Exact accrual on the cumulative basis
# --------------------------------------------------------------------------- #
def test_cumulative_exact_per_month_and_total(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    _enable(db, company, rate="12")  # monthly factor = 12/100/12 = 0.01
    _seed_rate(db, "2025-07-31", "40.0000")
    _seed_rate(db, "2025-08-31", "50.0000")
    _patch_cashflow(monkeypatch, [
        _row("2025-07", "-100000", "-100000"),  # financed 100000 @40 -> usd 2500
        _row("2025-08", "50000", "-50000"),      # financed 50000  @50 -> usd 1000
        _row("2025-09", "70000", "20000"),       # surplus -> 0
    ])

    r = financing.compute_financing_cost(db, project)
    assert r["enabled"] is True and r["basis"] == "cumulative"
    assert len(r["months"]) == 2
    m0, m1 = r["months"]
    assert m0["financed_try"] == "100000.00" and m0["interest_usd"] == "25.00" and m0["interest_try"] == "1000.00"
    assert m1["financed_try"] == "50000.00" and m1["interest_usd"] == "10.00" and m1["interest_try"] == "500.00"
    assert r["total_usd"] == "35.00"
    assert r["total_try"] == "1500.00"


# --------------------------------------------------------------------------- #
# Basis divergence: a net-negative month inside an overall surplus
# --------------------------------------------------------------------------- #
def test_cumulative_vs_net_divergence(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    _seed_rate(db, "2025-07-31", "40.0000")
    rows = [_row("2025-07", "-30000", "20000")]  # net negative, but still in surplus

    _enable(db, company, rate="12", basis="cumulative")
    _patch_cashflow(monkeypatch, rows)
    cum = financing.compute_financing_cost(db, project)
    assert cum["total_usd"] == "0.00" and cum["months"] == []  # financed nothing — in surplus

    _enable(db, company, rate="12", basis="net")
    net = financing.compute_financing_cost(db, project)
    assert net["basis"] == "net"
    # financed 30000 @40 -> usd 750 ; interest = 750*0.01 = 7.50 ; try = 30000*0.01 = 300.00
    assert net["total_usd"] == "7.50" and net["total_try"] == "300.00"


# --------------------------------------------------------------------------- #
# Toggle off -> zeroed, never raises
# --------------------------------------------------------------------------- #
def test_disabled_returns_zeroed(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    _seed_rate(db, "2025-07-31", "40.0000")
    _patch_cashflow(monkeypatch, [_row("2025-07", "-100000", "-100000")])
    r = financing.compute_financing_cost(db, project)  # company default = off
    assert r["enabled"] is False
    assert r["total_usd"] == "0.00" and r["total_try"] == "0.00" and r["months"] == []


def test_enabled_but_no_rate_returns_zeroed(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    company.financing_enabled = True  # no rate set
    db.commit()
    _patch_cashflow(monkeypatch, [_row("2025-07", "-100000", "-100000")])
    r = financing.compute_financing_cost(db, project)
    assert r["total_usd"] == "0.00" and r["months"] == []


# --------------------------------------------------------------------------- #
# Project override rate wins
# --------------------------------------------------------------------------- #
def test_project_override_rate_wins(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    _enable(db, company, rate="12")
    project.financing_annual_rate_pct_override = Decimal("6")  # half the company rate
    db.commit()
    _seed_rate(db, "2025-07-31", "40.0000")
    _patch_cashflow(monkeypatch, [_row("2025-07", "-100000", "-100000")])
    r = financing.compute_financing_cost(db, project)
    assert Decimal(r["annual_rate_pct"]) == Decimal("6")
    # factor = 6/100/12 = 0.005 ; usd 2500*0.005 = 12.50 ; try 100000*0.005 = 500.00
    assert r["total_usd"] == "12.50" and r["total_try"] == "500.00"


# --------------------------------------------------------------------------- #
# THE CRITICAL ONE — actuals are byte-identical on vs off
# --------------------------------------------------------------------------- #
def test_actuals_identical_financing_on_vs_off(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    _seed_rate(db, "2025-07-31", "40.0000")
    rows = [_row("2025-07", "-100000", "-100000")]

    # OFF
    _patch_cashflow(monkeypatch, rows)
    actual_off = financials.project_financials(db, project)["margin_pct"]
    fac_off = financials.forecast_at_completion(db, project)
    cost_count_off = db.query(CostEntry).filter(CostEntry.project_id == project.id).count()

    # ON
    _enable(db, company, rate="12")
    actual_on = financials.project_financials(db, project)["margin_pct"]
    fac_on = financials.forecast_at_completion(db, project)
    cost_count_on = db.query(CostEntry).filter(CostEntry.project_id == project.id).count()

    # Actual margin + the BASE forecast figures are byte-identical.
    assert actual_on == actual_off
    assert fac_on["forecast_final_cost_try"] == fac_off["forecast_final_cost_try"]
    assert fac_on["forecast_final_margin_pct"] == fac_off["forecast_final_margin_pct"]
    # Financing created no cost rows.
    assert cost_count_on == cost_count_off

    # Only the separable financing overlay moved.
    assert fac_off["financing_cost_try"] == "0.00"
    assert fac_off["forecast_final_margin_with_financing_pct"] == fac_off["forecast_final_margin_pct"]
    assert fac_on["financing_cost_try"] == "1000.00"  # 100000 * 0.01
    assert fac_on["forecast_final_cost_with_financing_try"] != fac_on["forecast_final_cost_try"]


# --------------------------------------------------------------------------- #
# Dashboard exposes the separate financing block
# --------------------------------------------------------------------------- #
def test_dashboard_exposes_financing_block(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    data = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]
    assert "financing" in data
    assert data["financing"]["enabled"] is False
    assert data["financing"]["total_try"] == "0.00"
    # Forecast block carries the separable financing keys.
    assert data["forecast_at_completion"]["financing_cost_try"] == "0.00"
