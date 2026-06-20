"""CR-031-C: revenue-model-aware Project P&L + m² analizi + kur-etkisi.

The riskiest sub-CR — it touches the financials payload. The two guard tests
(no-double-count + cost-untouched) are the headline acceptance criteria (§3.4).
No network: fx_rates seeded; conftest keeps live TCMB fetch off.
"""
import copy
from datetime import date
from decimal import Decimal

from app.calculations.pnl import fx_effect, m2_analysis, pnl_statement
from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.services import financials as fin_service
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
# Pure math
# --------------------------------------------------------------------------- #
def test_pnl_statement_financing_separable():
    s = pnl_statement(revenue_try="1000", revenue_usd="100", cost_try="600",
                      cost_usd="60", financing_try="50", financing_usd="5")
    assert s["net_excl_financing_try"] == "400.00"   # 1000 - 600
    assert s["net_incl_financing_try"] == "350.00"   # 1000 - 600 - 50
    # The separability invariant: excl − incl == financing total (§6).
    diff = Decimal(s["net_excl_financing_try"]) - Decimal(s["net_incl_financing_try"])
    assert diff == Decimal("50.00")
    assert s["margin_pct"] == "40.00"                # 400/1000


def test_pnl_statement_zero_revenue_guarded():
    s = pnl_statement("0", "0", "500", "50", "0", "0")
    assert s["margin_pct"] is None and s["margin_incl_financing_pct"] is None
    assert s["net_excl_financing_try"] == "-500.00"


def test_m2_analysis_exact_and_today_variant():
    m = m2_analysis("400000", "10000", "50", gross_m2="1000", net_m2="800",
                    unit_count=10, floor_count=5)
    assert m["per_gross_m2"]["try"] == "400.00"      # 400000/1000
    assert m["per_gross_m2"]["usd"] == "10.00"       # 10000/1000
    assert m["per_gross_m2"]["try_today"] == "500.00"  # (10000*50)/1000
    assert m["per_net_m2"]["try"] == "500.00"        # 400000/800
    assert m["per_unit"]["try"] == "40000.00"        # 400000/10
    assert m["per_floor"]["try"] == "80000.00"       # 400000/5


def test_m2_analysis_missing_area_is_null():
    m = m2_analysis("400000", "10000", "50", gross_m2=None, net_m2="0",
                    unit_count=None, floor_count=0)
    assert m["per_gross_m2"]["try"] is None          # no gross area
    assert m["per_net_m2"]["try"] is None            # zero net area → guarded
    assert m["per_unit"]["try"] is None
    assert m["per_floor"]["try"] is None


def test_fx_effect_exact_and_null_rate():
    e = fx_effect(cost_try_original="400000", cost_usd="10000", today_rate="50")
    assert e["cost_try_today"] == "500000.00"        # 10000 * 50
    assert e["fx_effect_try"] == "100000.00"         # 500000 - 400000
    assert e["fx_effect_pct"] == "25.00"             # 100000 / 400000
    # No today-rate → derived figures are null, never an exception.
    e2 = fx_effect("400000", "10000", None)
    assert e2["fx_effect_try"] is None and e2["today_rate"] is None


# --------------------------------------------------------------------------- #
# THE CRITICAL ONE — revenue-model-aware, no double-count (§0.2 / §3.4)
# --------------------------------------------------------------------------- #
def test_sell_side_counts_sales_and_landowner_only_not_invoices(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "kat_karsiligi")
    _seed_rate(db, "2025-03-01", "40.0000")
    # Cost (authoritative), a sale, a landowner payment — AND a hakediş invoice
    # that MUST be ignored for a sell-side model.
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "5000000", "sale_date": "2025-03-01"})
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-03-01", "amount_try": "2000000"})
    client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-X", "invoice_date": "2025-03-01", "amount_try": "9999999",
        "vat_rate": "0", "due_date": "2025-04-01"})

    block = sales_service.project_pnl(db, p)
    assert block["revenue_source"] == "sales"
    assert block["revenue_try"] == "7000000.00"      # 5,000,000 + 2,000,000 ONLY
    assert block["revenue_usd"] == "175000.00"       # 125,000 + 50,000
    assert block["revenue_breakdown"]["client_invoices_try"] == "0.00"  # invoice EXCLUDED


def test_hakedis_counts_invoices_only_not_sales(client, seed, db):
    pid = _login_dir(client, seed)
    p = seed["a"]["project"]  # default revenue_model == hakedis
    _seed_rate(db, "2025-03-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-1", "invoice_date": "2025-03-01", "amount_try": "3000000",
        "vat_rate": "0", "due_date": "2025-04-01"})
    # A stray unit sale on a hakediş project must NOT be counted as revenue.
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "Z-9", "net_m2": "50", "sale_price_try": "9999999", "sale_date": "2025-03-01"})

    block = sales_service.project_pnl(db, p)
    assert block["revenue_source"] == "hakedis"
    assert block["revenue_try"] == "3000000.00"      # invoices ONLY
    assert block["revenue_breakdown"]["unit_sales_try"] == "0.00"


# --------------------------------------------------------------------------- #
# THE OTHER CRITICAL ONE — cost stays authoritative & byte-identical (§0.2 / §3.4)
# --------------------------------------------------------------------------- #
def test_adding_sales_landowner_financing_leaves_cost_byte_identical(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "kat_karsiligi")
    _seed_rate(db, "2025-03-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "material_concrete",
        "amount_try": "400000", "vat_rate": "20"})

    # Snapshot the authoritative cost rollup BEFORE the sell-side layer exists.
    before = copy.deepcopy(fin_service.project_financials(db, p))

    # Now add a sale, a landowner payment, and turn financing ON.
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "5000000", "sale_date": "2025-03-01"})
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-03-01", "amount_try": "2000000"})
    company = seed["a"]["company"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12.00")
    db.add(company)
    db.commit()

    # Force a real recompute (drop the per-session input cache) and compare.
    db.info.pop("_project_inputs_cache", None)
    after = fin_service.project_financials(db, p)

    # Cost total, budget tree and margin internals are byte-identical (§0.2).
    assert after["forecast_final_cost_try"] == before["forecast_final_cost_try"]
    assert after["total_actual_with_vat_try"] == before["total_actual_with_vat_try"]
    assert after["total_committed_try"] == before["total_committed_try"]
    assert after["margin_pct"] == before["margin_pct"]
    assert after["categories"] == before["categories"]   # whole budget tree
    assert after == before                                # nothing perturbed


# --------------------------------------------------------------------------- #
# Financing separability over the real service (net excl − incl == financing)
# --------------------------------------------------------------------------- #
def test_financing_separable_in_project_pnl(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "yap_sat")
    _seed_rate(db, "2025-03-01", "40.0000")
    _seed_rate(db, "2025-03-31", "40.0000")
    # A cost (under the 500k approval threshold, so it isn't gated) with no
    # offsetting income → underwater month → nonzero financing.
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})
    client.post(f"/api/v1/projects/{pid}/unit-sales", json={
        "unit_label": "A-1", "net_m2": "100", "sale_price_try": "5000000", "sale_date": "2025-03-01"})
    company = seed["a"]["company"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12.00")
    db.add(company)
    db.commit()

    # today brackets the cost month so the rolling cashflow window sees the
    # underwater March (else the >1yr-old cost falls outside the window).
    block = sales_service.project_pnl(db, p, today=date(2025, 4, 1))
    fin_total = Decimal(block["financing_try"])
    assert fin_total > 0  # financing actually accrued (400,000 × 12%/12/mo while underwater)
    diff = Decimal(block["net_excl_financing_try"]) - Decimal(block["net_incl_financing_try"])
    assert diff == fin_total  # separable overlay — never folded into cost


# --------------------------------------------------------------------------- #
# m² + kur-etkisi over the real rollup; contractor split; payload surfacing
# --------------------------------------------------------------------------- #
def test_m2_and_fx_effect_over_real_rollup(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "kat_karsiligi", construction_gross_m2=Decimal("1000"),
                   construction_net_m2=Decimal("800"), unit_count=10,
                   contractor_share_pct=Decimal("60.00"))
    _seed_rate(db, "2025-03-01", "40.0000")   # cost snapshot date
    _seed_rate(db, "2025-12-01", "50.0000")   # latest → "today"
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "400000", "vat_rate": "0"})

    block = sales_service.project_pnl(db, p)
    m = block["m2_analysis"]
    assert m["per_gross_m2"]["try"] == "400.00"        # 400000/1000
    assert m["per_gross_m2"]["try_today"] == "500.00"  # (10000*50)/1000
    assert m["per_net_m2"]["try"] == "500.00"          # 400000/800
    assert m["per_unit"]["try"] == "40000.00"          # 400000/10

    kur = block["fx_effect"]
    assert kur["today_rate"] == "50.0000"
    assert kur["fx_effect_try"] == "100000.00"         # 10000*50 - 400000
    assert kur["fx_effect_pct"] == "25.00"

    # Contractor / landowner split present for share models, cost allocated by %.
    split = block["split"]
    assert split["contractor_share_pct"] == "60.00"
    assert split["contractor"]["allocated_cost_try"] == "240000.00"   # 400000 * 60%
    assert split["landowner"]["allocated_cost_try"] == "160000.00"


def test_dashboard_payload_includes_pnl_block(client, seed, db):
    pid = _login_dir(client, seed)
    _set_model(db, seed, "kat_karsiligi")
    r = client.get(f"/api/v1/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    pnl = r.json()["data"]["pnl"]
    assert pnl["revenue_source"] == "sales"
    assert "m2_analysis" in pnl and "fx_effect" in pnl
