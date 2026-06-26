"""CR-032 §6/§7 — Report Studio query engine guards.

Covers the §6 invariants with the same rigor as CR-031/CR-011:
zero-mutation, tenant isolation, no-double-count revenue parity, basis
correctness, parity with project_financials/forecast_at_completion, 422
robustness, coming_soon integrity (§6.7), and unit_type grain parity (§6.8).
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.ai_alert import AIAlert
from app.models.approval_request import ApprovalRequest
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate
from app.models.landowner_payment import LandownerPayment
from app.models.notification import Notification
from app.models.project import Project
from app.models.subcontractor import Subcontractor
from app.models.unit_sale import UnitSale
from app.models.vendor import Vendor
from app.responses import APIError
from app.services import financing as financing_service
from app.services import financials as fin_service
from app.services import sales as sales_service
from app.services.studio import engine

D = Decimal
TODAY = date(2026, 6, 30)

COUNTED_MODELS = [
    CostEntry, ClientInvoice, UnitSale, LandownerPayment, Project, BudgetLineItem,
    Vendor, Subcontractor, AIAlert, Notification, ApprovalRequest,
]


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _uid(seed, label="a"):
    return seed[label]["users"][ROLE_DIRECTOR].id


def _cost(db, p, amount, *, entry_type="actual", cat="material_steel", d=date(2026, 1, 10),
          commitment_id=None, amount_usd=None, payment_status="unpaid", vendor_id=None,
          subcategory=None, vat=D("0"), uid):
    amt = D(str(amount))
    c = CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category=cat,
        amount_try=amt, vat_amount_try=amt * vat, total_with_vat_try=amt * (D("1") + vat),
        amount_usd=(D(str(amount_usd)) if amount_usd is not None else None),
        payment_status=payment_status, entry_type=entry_type, commitment_id=commitment_id,
        subcategory=subcategory, vendor_id=vendor_id, created_by=uid,
    )
    db.add(c)
    db.flush()
    return c


def _sale(db, p, label, price, *, unit_type=None, net_m2=None, sale_date=date(2026, 1, 5), price_usd=None):
    s = UnitSale(
        project_id=p.id, company_id=p.company_id, unit_label=label, unit_type=unit_type,
        net_m2=(D(str(net_m2)) if net_m2 is not None else None), sale_price_try=D(str(price)),
        sale_price_usd=(D(str(price_usd)) if price_usd is not None else None), sale_date=sale_date,
    )
    db.add(s)
    db.flush()
    return s


def _invoice(db, p, amount, *, due=date(2026, 2, 15), uid):
    # outstanding_try is a GENERATED column (amount_try − amount_received_try) — never inserted.
    amt = D(str(amount))
    inv = ClientInvoice(
        project_id=p.id, company_id=p.company_id, invoice_number=f"HK-{amount}",
        invoice_date=date(2026, 1, 15), amount_try=amt, vat_amount_try=D("0"),
        total_with_vat_try=amt, net_due_try=amt, amount_received_try=D("0"),
        retention_amount_try=D("0"), due_date=due, created_by=uid,
    )
    db.add(inv)
    db.flush()
    return inv


def _set_sell_side(db, p, net_m2="200"):
    p.revenue_model = "kat_karsiligi"
    p.construction_net_m2 = D(net_m2)
    db.add(p)
    db.flush()


def _run(db, p_or_cid, spec, today=TODAY):
    cid = p_or_cid.company_id if isinstance(p_or_cid, Project) else p_or_cid
    return engine.run_spec(db, cid, spec, today=today)


def _counts(db):
    return {m.__name__: db.execute(select(func.count()).select_from(m)).scalar() for m in COUNTED_MODELS}


# --------------------------------------------------------------------------- #
# §6.1 — Zero mutation
# --------------------------------------------------------------------------- #
def test_zero_mutation_across_all_grains(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _set_sell_side(db, p)
    _cost(db, p, "100000", entry_type="actual", uid=uid)
    _cost(db, p, "50000", entry_type="committed", uid=uid)
    _sale(db, p, "A1", "1000000", unit_type="2+1", net_m2="80")
    _invoice(db, p, "70000", uid=uid)
    db.commit()

    before = _counts(db)
    specs = [
        {"metrics": ["cost_try", "open_commitment", "exposure"], "dimensions": ["cost_category", "month"]},
        {"metrics": ["revenue", "forecast_final", "margin_pct_current", "irr", "roi"], "dimensions": ["project"]},
        {"metrics": ["cash_in", "cash_out", "net_cash", "cum_cash"], "dimensions": ["month"]},
        {"metrics": ["unit_sales_revenue", "pnl", "gross_margin"], "dimensions": ["unit_type"]},
        {"metrics": ["cost_usd"], "basis": {"currency": "usd"}},
        {"metrics": ["cost_try"], "date_range": {"from": "2026-01-01", "to": "2026-01-31"},
         "comparison": {"preset": "previous_period"}},
        {"metrics": ["cost_try", "dso", "schedule_progress"], "dimensions": ["project"]},
    ]
    for spec in specs:
        _run(db, p, spec)
    db.flush()
    assert _counts(db) == before
    # Stronger than row counts: catch any in-place UPDATE/INSERT/DELETE staged on the session.
    assert not db.new and not db.dirty and not db.deleted


# --------------------------------------------------------------------------- #
# §6.2 — Tenant isolation (app-level company filter; works under SQLite w/o RLS)
# --------------------------------------------------------------------------- #
def test_tenant_isolation_company_a_never_sees_b(db, seed):
    pa, pb = seed["a"]["project"], seed["b"]["project"]
    _cost(db, pa, "100000", uid=_uid(seed, "a"))
    _cost(db, pb, "777777", uid=_uid(seed, "b"))
    db.commit()

    spec = {"metrics": ["cost_try"]}
    a_total = _run(db, pa.company_id, spec)["totals"]["metrics"]["cost_try"]
    b_total = _run(db, pb.company_id, spec)["totals"]["metrics"]["cost_try"]
    assert a_total == 100000.0
    assert b_total == 777777.0

    # Company A grouped by project never surfaces B's project name.
    rows = _run(db, pa.company_id, {"metrics": ["cost_try"], "dimensions": ["project"]})["rows"]
    names = {r["dims"]["project"] for r in rows}
    assert seed["a"]["project"].name in names
    assert seed["b"]["project"].name not in names

    # A filtering for B's project id yields nothing (B not in A's scope).
    leaked = _run(db, pa.company_id, {"metrics": ["cost_try"],
                                      "filters": [{"field": "project", "op": "=", "value": str(pb.id)}]})
    assert leaked["totals"]["metrics"]["cost_try"] in (None, 0.0)
    assert leaked["rows"] == []


# --------------------------------------------------------------------------- #
# §6.3 — No double-count: revenue routes through sales.project_pnl
# --------------------------------------------------------------------------- #
def test_revenue_parity_sell_side(db, seed):
    p = seed["a"]["project"]
    _set_sell_side(db, p)
    _sale(db, p, "A1", "1000000", unit_type="2+1", net_m2="80")
    _sale(db, p, "A2", "1500000", unit_type="3+1", net_m2="120")
    db.add(LandownerPayment(project_id=p.id, company_id=p.company_id, payer_name="Arsa",
                            payment_date=date(2026, 1, 1), amount_try=D("500000")))
    _invoice(db, p, "777777", uid=_uid(seed))  # a hakediş invoice MUST NOT inflate sell-side revenue
    _cost(db, p, "400000", uid=_uid(seed))
    db.commit()

    pnl = sales_service.project_pnl(db, p, today=TODAY)
    eng = _run(db, p, {"metrics": ["revenue"]})["totals"]["metrics"]["revenue"]
    assert eng == float(D(pnl["revenue_try"]))  # unit_sales + landowner, never client invoices
    assert eng == 3000000.0  # 1.0M + 1.5M units + 0.5M landowner — the 777777 invoice excluded


def test_revenue_parity_hakedis(db, seed):
    p = seed["a"]["project"]  # default revenue_model == hakedis
    _invoice(db, p, "300000", uid=_uid(seed))
    _sale(db, p, "X", "9999999", net_m2="50")  # must be EXCLUDED for hakedis
    db.commit()

    pnl = sales_service.project_pnl(db, p, today=TODAY)
    eng = _run(db, p, {"metrics": ["revenue"]})["totals"]["metrics"]["revenue"]
    assert eng == float(D(pnl["revenue_try"]))
    assert eng == 300000.0  # the hakediş invoice, NOT the stray unit sale


# --------------------------------------------------------------------------- #
# §6.4 — Basis correctness
# --------------------------------------------------------------------------- #
def test_basis_actual_vs_actual_plus_open(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    commit = _cost(db, p, "100000", entry_type="committed", uid=uid)
    _cost(db, p, "60000", entry_type="actual", commitment_id=commit.id, uid=uid)
    db.commit()

    fin = fin_service.project_financials(db, p)
    actual = _run(db, p, {"metrics": ["cost_try"], "basis": {"cost": "actual"}})["totals"]["metrics"]["cost_try"]
    apo = _run(db, p, {"metrics": ["cost_try"], "basis": {"cost": "actual_plus_open"}})["totals"]["metrics"]["cost_try"]
    open_c = _run(db, p, {"metrics": ["open_commitment"]})["totals"]["metrics"]["open_commitment"]
    exposure = _run(db, p, {"metrics": ["exposure"]})["totals"]["metrics"]["exposure"]

    assert actual == float(fin["total_actual_try"]) == 60000.0
    assert open_c == float(fin["total_open_committed_try"]) == 40000.0
    assert apo == 100000.0  # actual 60k + open 40k
    assert exposure == float(fin["total_committed_exposure_try"]) == 100000.0


def test_basis_currency_usd_matches_snapshots(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "100000", amount_usd="2500", entry_type="actual", uid=uid)
    _cost(db, p, "40000", amount_usd="1000", entry_type="actual", uid=uid)
    _cost(db, p, "30000", amount_usd=None, entry_type="actual", uid=uid)  # missing snapshot
    db.commit()

    res = _run(db, p, {"metrics": ["cost_usd"], "basis": {"currency": "usd"}})
    assert res["totals"]["metrics"]["cost_usd"] == 3500.0  # 2500 + 1000 (null skipped)
    assert res["meta"]["usd_missing_count"] == 1


def test_basis_vat_incl_uses_total_with_vat(db, seed):
    p = seed["a"]["project"]
    _cost(db, p, "100000", vat=D("0.20"), entry_type="actual", uid=_uid(seed))
    db.commit()
    excl = _run(db, p, {"metrics": ["cost_try"], "basis": {"vat": "excl"}})["totals"]["metrics"]["cost_try"]
    incl = _run(db, p, {"metrics": ["cost_try"], "basis": {"vat": "incl"}})["totals"]["metrics"]["cost_try"]
    assert excl == 100000.0
    assert incl == 120000.0


def test_basis_financing_wired_to_project_pnl(db, seed):
    p = seed["a"]["project"]
    _invoice(db, p, "500000", uid=_uid(seed))
    _cost(db, p, "200000", uid=_uid(seed))
    db.commit()
    pnl = sales_service.project_pnl(db, p, today=TODAY)
    excl = _run(db, p, {"metrics": ["net_profit_excl_fin"]})["totals"]["metrics"]["net_profit_excl_fin"]
    incl = _run(db, p, {"metrics": ["net_profit_incl_fin"]})["totals"]["metrics"]["net_profit_incl_fin"]
    assert excl == float(D(pnl["net_excl_financing_try"]))
    assert incl == float(D(pnl["net_incl_financing_try"]))
    # financing disabled by default ⇒ incl == excl (the non-zero case is below).
    assert excl == incl


def test_basis_financing_nonzero_difference_equals_financing_cost(db, seed):
    p = seed["a"]["project"]
    company = seed["a"]["company"]
    uid = _uid(seed)
    company.financing_enabled = True
    company.financing_annual_rate_pct = D("24")
    company.financing_basis = "cumulative"
    db.add(company)
    db.add(FxRate(rate_date=date(2026, 1, 1), usd_try=D("30.0")))  # cached rate for the underwater months
    _invoice(db, p, "100000", uid=uid)
    _cost(db, p, "500000", d=date(2026, 1, 10), uid=uid)  # big outflow → project runs underwater
    db.commit()

    fin = financing_service.compute_financing_cost(db, p, today=TODAY)
    assert D(fin["total_try"]) > 0  # financing is actually engaged
    pnl = sales_service.project_pnl(db, p, today=TODAY)
    excl = _run(db, p, {"metrics": ["net_profit_excl_fin"]})["totals"]["metrics"]["net_profit_excl_fin"]
    incl = _run(db, p, {"metrics": ["net_profit_incl_fin"]})["totals"]["metrics"]["net_profit_incl_fin"]
    assert excl == float(D(pnl["net_excl_financing_try"]))
    assert incl == float(D(pnl["net_incl_financing_try"]))
    # excl − incl is EXACTLY the financing total (CR-015 separable overlay).
    assert round(excl - incl, 2) == round(float(D(fin["total_try"])), 2)
    # The `pnl` metric flips with the financing basis toggle.
    pnl_excl = _run(db, p, {"metrics": ["pnl"], "basis": {"financing": "excl"}})["totals"]["metrics"]["pnl"]
    pnl_incl = _run(db, p, {"metrics": ["pnl"], "basis": {"financing": "incl"}})["totals"]["metrics"]["pnl"]
    assert pnl_excl == excl and pnl_incl == incl


# --------------------------------------------------------------------------- #
# §6.5 — Parity with existing surfaces
# --------------------------------------------------------------------------- #
def test_parity_cost_try_and_forecast_final(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "100000", entry_type="actual", uid=uid)
    _cost(db, p, "50000", entry_type="actual", uid=uid)
    _cost(db, p, "30000", entry_type="committed", uid=uid)
    db.commit()

    pf = fin_service.project_financials(db, p)
    fac = fin_service.forecast_at_completion(db, p)
    cost_try = _run(db, p, {"metrics": ["cost_try"], "basis": {"cost": "actual", "vat": "excl"}})
    forecast = _run(db, p, {"metrics": ["forecast_final"]})
    assert cost_try["totals"]["metrics"]["cost_try"] == float(pf["total_actual_try"])
    assert forecast["totals"]["metrics"]["forecast_final"] == float(D(fac["forecast_final_cost_try"]))


# --------------------------------------------------------------------------- #
# §6.6 — Robustness: malformed specs → 422 (never 500)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spec", [
    {"metrics": []},
    {"metrics": ["nope"]},
    {"metrics": ["cost_try"], "dimensions": ["block_phase"]},
    {"metrics": ["cost_try"], "filters": [{"field": "project", "op": "><", "value": "x"}]},
    {"metrics": ["cost_try"], "date_range": {"from": "2026-06-01", "to": "2026-01-01"}},
    {"metrics": ["cost_try"], "date_range": {"preset": "never_ever"}},
    {"metrics": ["cost_try"], "viz": "line", "chart": "x"},          # F-2: non-dict chart
    {"metrics": ["cost_try"], "viz": "line", "chart": {"x": "nope"}},  # F-2: unknown chart.x
    {"metrics": ["cost_try"], "viz": "line", "chart": {"y_left": "foo"}},  # F-2: non-list y_left
    {"metrics": ["cost_try"], "viz": "line", "chart": {"y_left": ["nope"]}},  # F-2: unknown y metric
])
def test_bad_spec_raises_422(db, seed, spec):
    with pytest.raises(APIError) as exc:
        _run(db, seed["a"]["project"], spec)
    assert exc.value.status_code == 422


# --------------------------------------------------------------------------- #
# §6.7 — Coming-soon integrity
# --------------------------------------------------------------------------- #
def test_coming_soon_returns_null_plus_meta_unavailable(db, seed):
    p = seed["a"]["project"]
    _cost(db, p, "100000", uid=_uid(seed))
    db.commit()
    res = _run(db, p, {"metrics": ["cost_try", "dso", "schedule_progress"], "dimensions": ["project"]})
    assert "dso" in res["meta"]["unavailable"] and "schedule_progress" in res["meta"]["unavailable"]
    assert "cost_try" not in res["meta"]["unavailable"]
    for row in res["rows"]:
        assert row["metrics"]["dso"] is None
        assert row["metrics"]["schedule_progress"] is None
        assert row["metrics"]["cost_try"] is not None  # available field never silently null


def test_available_grain_mismatch_nulls_silently_not_unavailable(db, seed):
    p = seed["a"]["project"]
    _cost(db, p, "100000", uid=_uid(seed))
    db.commit()
    # cost_try (cost grain) cannot be sliced by unit_type (unit grain) → graceful, no raise.
    res = _run(db, p, {"metrics": ["cost_try"], "dimensions": ["unit_type"]})
    assert res["rows"] == []
    assert "cost_try" not in res["meta"]["unavailable"]


def test_grain_incompatible_cell_nulls_beside_valid_unit_metric(db, seed):
    # The precise §6.7 wording: an available-but-grain-incompatible cell nulls
    # SILENTLY beside a populated valid cell — and is NOT listed in meta.unavailable.
    p = seed["a"]["project"]
    _set_sell_side(db, p)
    _sale(db, p, "A1", "1000000", unit_type="2+1", net_m2="80")
    _cost(db, p, "100000", uid=_uid(seed))
    db.commit()
    res = _run(db, p, {"metrics": ["unit_sales_revenue", "cost_try"], "dimensions": ["unit_type"]})
    assert len(res["rows"]) >= 1
    for r in res["rows"]:
        assert r["metrics"]["unit_sales_revenue"] is not None  # unit grain ✓
        assert r["metrics"]["cost_try"] is None                # cost grain can't slice unit_type
    assert "cost_try" not in res["meta"]["unavailable"]        # available, just grain-incompatible


def test_cash_by_revenue_model_degrades_gracefully(db, seed):
    # Regression for F-1: a cash metric sliced by revenue_model must degrade to an
    # empty result, NOT raise a 500 (the catalog no longer claims cash compatibility).
    p = seed["a"]["project"]
    _cost(db, p, "100000", uid=_uid(seed))
    db.commit()
    res = _run(db, p, {"metrics": ["cash_in"], "dimensions": ["revenue_model"]})
    assert res["rows"] == []


# --------------------------------------------------------------------------- #
# §6.8 — unit_type grain parity (no allocation drift)
# --------------------------------------------------------------------------- #
def test_unit_type_grain_reconciles_to_unit_sales_pnl(db, seed):
    p = seed["a"]["project"]
    _set_sell_side(db, p, net_m2="300")
    _sale(db, p, "A1", "1000000", unit_type="2+1", net_m2="80")
    _sale(db, p, "A2", "900000", unit_type="2+1", net_m2="70")
    _sale(db, p, "B1", "1500000", unit_type="3+1", net_m2="120")
    _sale(db, p, "C1", "600000", unit_type=None, net_m2="30")  # null → "(belirtilmemiş)"
    _cost(db, p, "1200000", uid=_uid(seed))
    db.commit()

    pnl = sales_service.unit_sales_pnl(db, p, today=TODAY)
    totals = pnl["totals"]
    res = _run(db, p, {"metrics": ["unit_sales_revenue", "pnl", "gross_margin", "margin_pct_current"],
                       "dimensions": ["unit_type"]})
    rows = {tuple(r["dims"].values())[0]: r["metrics"] for r in res["rows"]}
    assert "(belirtilmemiş)" in rows  # null unit_type bucketed, still counted

    # Σ groups == project unit-sales totals (no drift).
    sum_rev = sum(m["unit_sales_revenue"] for m in rows.values())
    sum_pnl = sum(m["pnl"] for m in rows.values())
    assert round(sum_rev, 2) == float(D(totals["sale_price_try"]))
    assert round(sum_pnl, 2) == float(D(totals["pnl_try"]))

    # group margin == Σpnl/Σrevenue (not an average of per-unit margins).
    two_plus = rows["2+1"]
    assert two_plus["margin_pct_current"] == pytest.approx(
        round(two_plus["pnl"] / two_plus["unit_sales_revenue"] * 100, 2), abs=0.01)


# --------------------------------------------------------------------------- #
# Grouping / time buckets
# --------------------------------------------------------------------------- #
def test_time_buckets_partition_without_leakage(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "10000", d=date(2025, 12, 31), uid=uid)
    _cost(db, p, "20000", d=date(2026, 1, 10), uid=uid)
    _cost(db, p, "30000", d=date(2026, 2, 15), uid=uid)
    _cost(db, p, "40000", d=date(2026, 4, 20), uid=uid)
    db.commit()

    total = _run(db, p, {"metrics": ["cost_try"]})["totals"]["metrics"]["cost_try"]
    for dim, expect_keys in [
        ("month", {"2025-12", "2026-01", "2026-02", "2026-04"}),
        ("quarter", {"2025-Q4", "2026-Q1", "2026-Q2"}),
        ("year", {"2025", "2026"}),
    ]:
        res = _run(db, p, {"metrics": ["cost_try"], "dimensions": [dim]})
        keys = {r["dims"][dim] for r in res["rows"]}
        assert keys == expect_keys
        assert round(sum(r["metrics"]["cost_try"] for r in res["rows"]), 2) == total

    weeks = _run(db, p, {"metrics": ["cost_try"], "dimensions": ["week"]})["rows"]
    assert all(r["dims"]["week"].count("-W") == 1 for r in weeks)


def test_payment_status_groups_by_stored_four_values(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    for status, amt in [("paid", "1000"), ("partial", "2000"), ("overdue", "3000"), ("unpaid", "4000")]:
        _cost(db, p, amt, payment_status=status, uid=uid)
    db.commit()
    res = _run(db, p, {"metrics": ["cost_try"], "dimensions": ["payment_status"]})
    got = {r["dims"]["payment_status"]: r["metrics"]["cost_try"] for r in res["rows"]}
    assert got == {"paid": 1000.0, "partial": 2000.0, "overdue": 3000.0, "unpaid": 4000.0}


# --------------------------------------------------------------------------- #
# Comparison window + deltas
# --------------------------------------------------------------------------- #
def test_previous_period_comparison_and_delta(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "100000", d=date(2026, 1, 15), uid=uid)
    _cost(db, p, "50000", d=date(2025, 12, 15), uid=uid)
    db.commit()
    res = _run(db, p, {"metrics": ["cost_try"],
                       "date_range": {"from": "2026-01-01", "to": "2026-01-31"},
                       "comparison": {"preset": "previous_period"}, "comparison_unit": "pct"})
    assert res["totals"]["metrics"]["cost_try"] == 100000.0
    assert res["meta"]["comparison"] == {"from": "2025-12-01", "to": "2025-12-31"}
    assert res["totals"]["deltas"]["cost_try"] == pytest.approx(1.0)  # (100k-50k)/50k

    res_abs = _run(db, p, {"metrics": ["cost_try"],
                           "date_range": {"from": "2026-01-01", "to": "2026-01-31"},
                           "comparison": {"preset": "previous_period"}, "comparison_unit": "abs"})
    assert res_abs["totals"]["deltas"]["cost_try"] == 50000.0  # 100k − 50k (absolute)


def test_preset_aliases_resolve_english_and_turkish(db, seed):
    # §3.3 "accept both": English alias and Turkish resolver preset map identically.
    p = seed["a"]["project"]
    _cost(db, p, "1000", uid=_uid(seed))
    db.commit()
    today = date(2026, 6, 30)
    en = _run(db, p, {"metrics": ["cost_try"], "date_range": {"preset": "last_6_months"}}, today=today)
    tr = _run(db, p, {"metrics": ["cost_try"], "date_range": {"preset": "son_6_ay"}}, today=today)
    assert en["meta"]["date_range"] == tr["meta"]["date_range"]
    assert en["meta"]["date_range"]["to"] == "2026-06-30"
    ytd = _run(db, p, {"metrics": ["cost_try"], "date_range": {"preset": "ytd"}}, today=today)
    assert ytd["meta"]["date_range"] == {"from": "2026-01-01", "to": "2026-06-30"}


# --------------------------------------------------------------------------- #
# Sort / limit / truncation + series
# --------------------------------------------------------------------------- #
def test_sort_limit_and_truncation(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "10000", d=date(2026, 1, 1), uid=uid)
    _cost(db, p, "30000", d=date(2026, 2, 1), uid=uid)
    _cost(db, p, "20000", d=date(2026, 3, 1), uid=uid)
    db.commit()
    res = _run(db, p, {"metrics": ["cost_try"], "dimensions": ["month"],
                       "sort": {"by": "cost_try", "dir": "desc"}, "limit": 2})
    assert res["meta"]["truncated"] is True
    assert len(res["rows"]) == 2
    vals = [r["metrics"]["cost_try"] for r in res["rows"]]
    assert vals == [30000.0, 20000.0]  # desc, top-2


def test_series_emitted_for_line_viz(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "10000", d=date(2026, 1, 1), uid=uid)
    _cost(db, p, "20000", d=date(2026, 2, 1), uid=uid)
    db.commit()
    res = _run(db, p, {"viz": "line", "metrics": ["cost_try"], "dimensions": ["month"],
                       "chart": {"x": "month", "y_left": ["cost_try"]}})
    assert "series" in res
    s = res["series"][0]
    assert s["metric"] == "cost_try"
    assert [pt["x"] for pt in s["points"]] == ["2026-01", "2026-02"]
    assert [pt["y"] for pt in s["points"]] == [10000.0, 20000.0]


def test_table_viz_has_no_series(db, seed):
    p = seed["a"]["project"]
    _cost(db, p, "10000", uid=_uid(seed))
    db.commit()
    res = _run(db, p, {"viz": "table", "metrics": ["cost_try"], "dimensions": ["project"]})
    assert "series" not in res
