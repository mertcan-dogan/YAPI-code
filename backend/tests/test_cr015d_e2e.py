"""CR-015-D: consolidated end-to-end pass over financing cost.

Unlike test_cr015b (which monkeypatches the cashflow for exact math), this drives
a GENUINELY negative cumulative month through real cost/invoice rows + the real
project_cashflow, then asserts: exact accrual on the cumulative basis, the
dashboard exposes the financing block + forecast_*_with_financing keys, ACTUALS
are byte-identical on vs off (no cost_entry created), a project override changes
the accrual, and company isolation holds. Dialect-safe (SQLite, fx seeded).
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate
from app.models.project import Project
from app.services import financials, financing


def _next_month(d: date) -> tuple[int, int]:
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def test_financing_end_to_end(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    company, project = seed["a"]["company"], seed["a"]["project"]
    pid = project.id

    today = date.today()
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1])
    ny, nm = _next_month(today)
    due = date(ny, nm, 15)

    # Real rows: an actual cost THIS month (outflow) and a large invoice due NEXT
    # month (planned inflow) so the cumulative position is negative for exactly the
    # current month, then restored to surplus — independent of window size.
    db.add(FxRate(rate_date=month_end, usd_try=Decimal("40.0000")))
    db.commit()
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": today.isoformat(), "cost_category": "other",
        "amount_try": "200000", "vat_rate": "20",  # total_with_vat = 240000
    })
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "FIN-E2E-1", "invoice_date": today.isoformat(),
        "amount_try": "2000000", "vat_rate": "0", "due_date": due.isoformat(),
    })
    assert r.status_code == 200, r.text

    # --- Baseline (financing OFF): capture actuals + base forecast ---
    actual_off = financials.project_financials(db, project)["margin_pct"]
    fac_off = financials.forecast_at_completion(db, project)
    cost_count_off = db.query(CostEntry).filter(CostEntry.project_id == pid).count()
    assert fac_off["financing_cost_try"] == "0.00"

    # --- Enable company financing @ 10% cumulative ---
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("10")
    company.financing_basis = "cumulative"
    db.commit()

    # Exact accrual on the single underwater month: financed 240000 @ 40.
    #   interest_try = 240000 * 10/100/12 = 2000.00
    #   interest_usd = (240000/40) * 10/100/12 = 6000 * 0.0083... = 50.00
    fin = financing.compute_financing_cost(db, project, today=today)
    assert fin["enabled"] is True and fin["basis"] == "cumulative"
    assert len(fin["months"]) == 1
    assert fin["months"][0]["financed_try"] == "240000.00"
    assert fin["total_try"] == "2000.00"
    assert fin["total_usd"] == "50.00"

    # --- Dashboard exposes the financing block + the forecast overlay keys ---
    dash = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]
    assert dash["financing"]["enabled"] is True
    assert dash["financing"]["total_try"] == "2000.00"
    fac_on = dash["forecast_at_completion"]
    assert fac_on["financing_cost_try"] == "2000.00"
    assert "forecast_final_cost_with_financing_try" in fac_on
    assert "forecast_final_margin_with_financing_pct" in fac_on

    # --- THE CRITICAL INVARIANT: actuals byte-identical on vs off ---
    actual_on = financials.project_financials(db, project)["margin_pct"]
    cost_count_on = db.query(CostEntry).filter(CostEntry.project_id == pid).count()
    assert actual_on == actual_off                                  # actual margin unchanged
    assert fac_on["forecast_final_cost_try"] == fac_off["forecast_final_cost_try"]    # base forecast unchanged
    assert fac_on["forecast_final_margin_pct"] == fac_off["forecast_final_margin_pct"]
    assert cost_count_on == cost_count_off                          # financing created no cost_entry
    # Only the separable overlay moved.
    assert fac_on["forecast_final_cost_with_financing_try"] != fac_on["forecast_final_cost_try"]

    # --- Project override (different rate) changes the accrual ---
    project.financing_annual_rate_pct_override = Decimal("20")  # double the company rate
    db.commit()
    fin_override = financing.compute_financing_cost(db, project, today=today)
    assert fin_override["total_try"] == "4000.00"   # 240000 * 20/100/12
    assert fin_override["total_usd"] == "100.00"

    # --- Company isolation: B cannot read A's dashboard / financing ---
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"/api/v1/projects/{pid}/dashboard").status_code == 404
