"""PERF: the financing/dashboard read path must NEVER make a synchronous TCMB
fetch — even when the project timeline runs past the cached FX rates.

Before this fix ``compute_financing_cost`` called ``fx.rate_as_of`` per underwater
month; with live fetch on (prod default), each uncached/future month triggered a
blocking 10s TCMB HTTP call + a day-by-day walk-back of more calls → minutes per
dashboard. Now rates are resolved CACHE-ONLY in one batched query. These tests
pin that: ``_fetch_tcmb_rate`` is never called, and the result is computed fast
using the most recent cached rate.
"""
import time
from datetime import date
from decimal import Decimal

from app.config import settings
from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.services import financials, financing
from app.services import fx as fx_service


def _spy_no_fetch(monkeypatch):
    """Count TCMB fetches; simulate prod by turning live fetch ON."""
    calls = {"n": 0}

    def _counting_fetch(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(settings, "fx_live_fetch", True)  # prod-like
    monkeypatch.setattr(fx_service, "_fetch_tcmb_rate", _counting_fetch)
    return calls


def _many_underwater_months():
    """36 months 2025-01..2027-12, every month underwater (well past any cache)."""
    rows = []
    cum = 0
    for i in range(36):
        y = 2025 + i // 12
        m = i % 12 + 1
        cum -= 10000
        rows.append({"month": f"{y}-{m:02d}", "year": y, "month_num": m,
                     "net_try": Decimal("-10000"), "cumulative_try": Decimal(cum)})
    return rows


def test_financing_uses_cache_only_no_network(seed, db, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12")  # monthly factor 0.01
    company.financing_basis = "cumulative"
    # Exactly ONE cached rate, far before the project's later months.
    db.add(FxRate(rate_date=date(2025, 1, 31), usd_try=Decimal("30.0000")))
    db.commit()

    calls = _spy_no_fetch(monkeypatch)
    monkeypatch.setattr(financials, "project_cashflow", lambda db, project, today=None: _many_underwater_months())

    t0 = time.perf_counter()
    r = financing.compute_financing_cost(db, project)
    elapsed = time.perf_counter() - t0

    # NO network call happened despite 36 months past the cached rate.
    assert calls["n"] == 0
    # All 36 underwater months modeled, using the latest cached rate (30.0).
    assert len(r["months"]) == 36
    assert all(m["rate"] == "30.0000" for m in r["months"])
    # interest_try is rate-independent: 10000*0.01, 20000*0.01, ... summed.
    assert r["total_try"] == "66600.00"  # Σ 0.01*10000*i for i=1..36 = 100*666
    assert Decimal(r["total_usd"]) > 0
    # Pure in-process compute — trivially fast (no 10s-per-month network).
    assert elapsed < 1.0, f"financing compute too slow: {elapsed:.3f}s"


def test_dashboard_read_path_makes_no_fx_fetch(client, db, seed, monkeypatch):
    company, project = seed["a"]["company"], seed["a"]["project"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12")
    db.add(FxRate(rate_date=date(2025, 1, 31), usd_try=Decimal("30.0000")))
    db.commit()

    calls = _spy_no_fetch(monkeypatch)
    monkeypatch.setattr(financials, "project_cashflow", lambda db, project, today=None: _many_underwater_months())

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    t0 = time.perf_counter()
    r = client.get(f"/api/v1/projects/{project.id}/dashboard")
    elapsed = time.perf_counter() - t0

    assert r.status_code == 200, r.text
    # The whole dashboard (financing + pnl both call compute_financing_cost) made
    # ZERO synchronous TCMB fetches.
    assert calls["n"] == 0
    data = r.json()["data"]
    assert data["financing"]["total_try"] == "66600.00"
    assert data["degraded_sections"] == []  # nothing failed
    assert elapsed < 2.0, f"dashboard too slow: {elapsed:.3f}s"
