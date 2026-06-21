"""CR-031 post-deploy bug fixes.

BUG 1 — ``ProjectOut`` never serialized ``revenue_model`` / ``contractor_share_pct``,
so the Satışlar & Kar/Zarar page fell back to "hakedis" for its sell-side-vs-hakediş
banner/editor gating on EVERY project, disagreeing with the backend's
revenue_source-driven P&L label. Guard: the project payload (and the dashboard's
``project`` sub-object) expose ``revenue_model``, and a hakediş project's P&L
``revenue_source`` reads "hakedis".

BUG 2 — the IRR/cashflow OUTFLOWS used VAT-inclusive ``total_with_vat_try`` while
the P&L Maliyet uses the ex-VAT ``forecast_final_cost`` rollup, so IRR outflows
came out as the P&L cost × the VAT rate. Guard: Σ(cashflow outflows TRY) == P&L
Maliyet == dashboard ``forecast_final_cost_try`` (three-way agreement), on an
ex-VAT basis. Cost stays read-only (no cost_entry mutated).
"""
from datetime import date
from decimal import Decimal

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
# BUG 1 — revenue_model must reach the frontend (root cause of the wrong gating)
# --------------------------------------------------------------------------- #
def test_project_payload_exposes_revenue_model_and_share(client, seed, db):
    pid = _login_dir(client, seed)
    _set_model(db, seed, "kat_karsiligi", contractor_share_pct=Decimal("60.00"))
    proj = client.get(f"/api/v1/projects/{pid}").json()["data"]
    # Without these fields the page silently defaults to "hakedis" gating, so the
    # banner says hakediş while the P&L label says "Satış + Arsa Sahibi".
    assert proj["revenue_model"] == "kat_karsiligi"
    assert proj["contractor_share_pct"] == "60.00"


def test_dashboard_project_subobject_exposes_revenue_model(client, seed, db):
    pid = _login_dir(client, seed)
    _set_model(db, seed, "yap_sat")
    r = client.get(f"/api/v1/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["project"]["revenue_model"] == "yap_sat"


def test_hakedis_project_pnl_source_reads_hakedis(client, seed, db):
    """A hakediş project's P&L source is 'hakedis' → the page label is 'Hakediş',
    and the project payload agrees so the banner + label can't disagree."""
    pid = _login_dir(client, seed)
    p = seed["a"]["project"]  # default revenue_model == hakedis
    _seed_rate(db, "2025-03-01", "40.0000")
    client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-1", "invoice_date": "2025-03-01", "amount_try": "3000000",
        "vat_rate": "0", "due_date": "2025-04-01"})

    assert sales_service.project_pnl(db, p)["revenue_source"] == "hakedis"
    assert client.get(f"/api/v1/projects/{pid}").json()["data"]["revenue_model"] == "hakedis"


# --------------------------------------------------------------------------- #
# BUG 2 — IRR/cashflow outflows share the P&L's ex-VAT cost basis (no × VAT)
# --------------------------------------------------------------------------- #
def test_cashflow_outflows_match_pnl_cost_ex_vat(client, seed, db):
    pid = _login_dir(client, seed)
    p = _set_model(db, seed, "kat_karsiligi")
    _seed_rate(db, "2025-03-01", "40.0000")
    # A 20%-VAT cost (under the 500k auto-approval gate): amount_try ex-VAT
    # 400,000; total_with_vat_try 480,000. The old code summed the 480,000.
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "material_concrete",
        "amount_try": "400000", "vat_rate": "20"})

    pnl_cost = Decimal(sales_service.project_pnl(db, p)["cost_try"])
    assert pnl_cost == Decimal("400000.00")  # ex-VAT authoritative rollup

    try_flows, _usd = sales_service.cashflow_series(db, p)
    outflows = -sum((amt for _d, amt in try_flows if amt < 0), Decimal(0))
    # Σ outflows uses the SAME ex-VAT basis as the P&L Maliyet — not × 1.20.
    assert outflows == pnl_cost
    assert outflows != pnl_cost * Decimal("1.20")  # the exact bug we fixed

    # Three-way agreement: dashboard cost figure == P&L cost == Σ outflows.
    dash = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]
    assert Decimal(dash["financials"]["forecast_final_cost_try"]) == pnl_cost
    assert Decimal(dash["pnl"]["cost_try"]) == pnl_cost
