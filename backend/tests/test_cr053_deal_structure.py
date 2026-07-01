"""CR-053 — per-project deal structure + the founder's OPERATOR P&L model.

The operator model (§0), all DATA-DRIVEN (not deal_structure-driven):
* sell-side REVENUE = the contractor's OWN flat sales (unit_sales owner_side=yuklenici)
  + CASH landowner contributions (landowner_payments). The landowner's own
  (arsa_sahibi) sales and the contributed (non-cash) LAND are EXCLUDED from revenue.
* COST = the authoritative construction rollup (already includes the given-away
  flats) + rent support (kira_yardimi). The land is NEVER a separate cost — its cost
  is embodied in the construction; it is surfaced as *efektif arsa maliyeti*
  (= construction × landowner share), derived read-time, never added to revenue/cost.
* The planned split: contractor sellable vs landowner units/m², sold + remaining.

Guards extend CR-031/047's no-double-count discipline. SQLite via conftest, no
network (fx live fetch off).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import COST_CATEGORIES, ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.landowner_payment import LandownerPayment
from app.models.project import Project
from app.models.project_unit import ProjectUnit
from app.models.unit_sale import UnitSale
from app.models.user import User
from app.services import financials as fin
from app.services import sales as sales_service

D = Decimal
TODAY = date(2026, 6, 30)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _uid(db, p):
    return db.execute(select(User.id).where(User.company_id == p.company_id)).scalars().first()


def _sellside(db, seed, model="kat_karsiligi", label="a", **extra):
    p = seed[label]["project"]
    p.revenue_model = model
    for k, v in extra.items():
        setattr(p, k, v)
    db.add(p)
    db.flush()
    return p


def _sale(db, p, amount, d=date(2025, 6, 1), *, owner="yuklenici", label="Daire"):
    db.add(UnitSale(project_id=p.id, company_id=p.company_id, unit_label=label,
                    sale_price_try=D(str(amount)), sale_date=d, owner_side=owner))
    db.flush()


def _unit(db, p, count, gross, *, owner="yuklenici", price=None):
    db.add(ProjectUnit(project_id=p.id, company_id=p.company_id, unit_type="2+1",
                       count=count, gross_m2_each=D(str(gross)), owner_side=owner,
                       sale_price_try=D(str(price)) if price is not None else None))
    db.flush()


def _cost(db, p, amount, *, cat="material_steel", d=date(2025, 3, 1)):
    amt = D(str(amount))
    db.add(CostEntry(project_id=p.id, company_id=p.company_id, entry_date=d,
                     cost_category=cat, amount_try=amt, vat_amount_try=D("0"),
                     total_with_vat_try=amt, amount_paid_try=D("0"),
                     payment_status="unpaid", entry_type="actual", created_by=_uid(db, p)))
    db.flush()


def _landowner(db, p, amount, d=date(2025, 3, 1)):
    db.add(LandownerPayment(project_id=p.id, company_id=p.company_id, payer_name="Arsa Sahibi",
                            payment_date=d, amount_try=D(str(amount))))
    db.flush()


def _pnl(db, p):
    """project_pnl after expiring identity-mapped state so project.units reloads."""
    db.expire_all()
    return sales_service.project_pnl(db, db.get(Project, p.id), today=TODAY)


# --------------------------------------------------------------------------- #
# kira_yardimi is a real, valid cost category (app-level, no migration)
# --------------------------------------------------------------------------- #
def test_kira_yardimi_is_a_cost_category():
    assert COST_CATEGORIES["kira_yardimi"] == "Kira Yardımı"


# --------------------------------------------------------------------------- #
# §3 — revenue: yuklenici sales + cash; EXCLUDE arsa_sahibi sales + non-cash land
# --------------------------------------------------------------------------- #
def test_revenue_excludes_arsa_sahibi_sales_and_land_includes_yuklenici_and_cash(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "5000000", owner="yuklenici")
    _sale(db, p, "3000000", owner="arsa_sahibi")    # the landowner's flat — EXCLUDED
    _landowner(db, p, "1000000")                    # cash contribution — INCLUDED
    _cost(db, p, "2000000")
    db.commit()

    rc = sales_service.revenue_cost_totals(db, p, today=TODAY)
    assert rc["revenue_source"] == "sales"
    assert rc["revenue_try"] == D("6000000")        # 5,000,000 yuklenici + 1,000,000 cash ONLY
    bd = rc["revenue_breakdown"]
    assert bd["unit_sales_try"] == "5000000.00"     # the contractor's own (yuklenici) sales
    assert bd["arsa_sahibi_sales_try"] == "3000000.00"  # surfaced but excluded from revenue
    assert bd["landowner_try"] == "1000000.00"
    assert bd["client_invoices_try"] == "0.00"      # hakediş never leaks in
    assert rc["cost_try"] == D("2000000")


# --------------------------------------------------------------------------- #
# §3 — cost = construction + kira_yardimi; the LAND is never a separate cost
# --------------------------------------------------------------------------- #
def test_cost_includes_kira_yardimi_and_rent_support_is_normal_cost(db, seed):
    p = _sellside(db, seed)
    _cost(db, p, "3000000", cat="material_concrete")
    _cost(db, p, "1000000", cat="kira_yardimi")     # rent support → normal cost
    _sale(db, p, "6000000", owner="yuklenici")
    db.commit()

    rc = sales_service.revenue_cost_totals(db, p, today=TODAY)
    assert rc["cost_try"] == D("4000000")           # 3M construction + 1M kira yardımı
    assert rc["revenue_try"] == D("6000000")


def test_land_never_enters_cost_rollup_byte_identical(db, seed):
    # Extends the CR-031/047 no-double-count guard: tagging landowner (non-cash land)
    # units and recording an arsa_sahibi sale must NOT perturb the authoritative cost.
    p = _sellside(db, seed)
    _cost(db, p, "5000000")
    db.commit()
    before = dict(fin.project_financials(db, p, today=TODAY))

    _unit(db, p, 4, "100", owner="arsa_sahibi")     # the contributed (non-cash) land
    _sale(db, p, "3000000", owner="arsa_sahibi")    # the landowner's own flat sale
    db.commit()
    db.info.pop("_project_inputs_cache", None)
    after = fin.project_financials(db, p, today=TODAY)

    assert after["forecast_final_cost_try"] == before["forecast_final_cost_try"]
    assert after["categories"] == before["categories"]
    assert after == before                          # land/arsa-sahibi sale perturb nothing


# --------------------------------------------------------------------------- #
# §4 — efektif arsa maliyeti = construction × landowner share
# --------------------------------------------------------------------------- #
def test_efektif_arsa_maliyeti_explicit_split(db, seed):
    p = _sellside(db, seed)
    _cost(db, p, "5000000")
    _unit(db, p, 6, "100", owner="yuklenici")       # contractor: 600 m²
    _unit(db, p, 4, "100", owner="arsa_sahibi")     # landowner:  400 m²  → share 40%
    db.commit()

    block = _pnl(db, p)
    assert block["landowner_share_basis"] == "units"
    assert block["landowner_share_pct"] == "40.00"
    assert block["efektif_arsa_maliyeti_try"] == "2000000.00"   # 5,000,000 × 0.40
    # Derived/informational ONLY — never folded into cost or revenue.
    assert block["cost_try"] == "5000000.00"


def test_efektif_arsa_maliyeti_pct_fallback(db, seed):
    # No per-unit schedule → fall back to (1 − contractor_share_pct).
    p = _sellside(db, seed, contractor_share_pct=D("60.00"))
    _cost(db, p, "1000000")
    db.commit()

    block = _pnl(db, p)
    assert block["landowner_share_basis"] == "pct"
    assert block["landowner_share_pct"] == "40.00"              # 100 − 60
    assert block["efektif_arsa_maliyeti_try"] == "400000.00"    # 1,000,000 × 0.40


def test_efektif_arsa_maliyeti_null_when_no_basis(db, seed):
    p = _sellside(db, seed)                          # no schedule, no contractor_share_pct
    _cost(db, p, "1000000")
    db.commit()

    block = _pnl(db, p)
    assert block["landowner_share_basis"] is None
    assert block["efektif_arsa_maliyeti_try"] is None
    assert block["landowner_share_pct"] is None


# --------------------------------------------------------------------------- #
# §2 — the planned split: sellable / sold / remaining + projected value
# --------------------------------------------------------------------------- #
def test_planned_split_sellable_sold_remaining(db, seed):
    p = _sellside(db, seed)
    _unit(db, p, 6, "100", owner="yuklenici", price="1000000")  # sellable 6, est 6M
    _unit(db, p, 4, "120", owner="arsa_sahibi")                 # landowner 4
    _sale(db, p, "1000000", owner="yuklenici")
    _sale(db, p, "1000000", owner="yuklenici")                  # 2 sold
    db.commit()

    split = _pnl(db, p)["planned_split"]
    assert split["has_schedule"] is True
    assert split["contractor"]["units"] == 6
    assert split["landowner"]["units"] == 4
    assert split["sold"]["units"] == 2
    assert split["sold"]["value_try"] == "2000000.00"
    assert split["remaining"]["units"] == 4
    assert split["remaining"]["projected_value_try"] == "4000000.00"   # 6M × 4/6


# --------------------------------------------------------------------------- #
# §7 — the worked example reconciles end-to-end
# build 10 / give 4 / sell 6 @1M, cost 5M → revenue 6M, cost 5M, profit 1M,
# efektif arsa maliyeti = 5M × 4/10 = 2M
# --------------------------------------------------------------------------- #
def test_worked_example_reconciles(db, seed):
    p = _sellside(db, seed)
    _unit(db, p, 6, "100", owner="yuklenici")       # 6 to sell
    _unit(db, p, 4, "100", owner="arsa_sahibi")     # 4 given to the landowner
    for _ in range(6):
        _sale(db, p, "1000000", owner="yuklenici")  # sell all 6 @ 1M = 6M
    _cost(db, p, "5000000")                          # construction cost 5M
    db.commit()

    block = _pnl(db, p)
    assert block["revenue_try"] == "6000000.00"
    assert block["cost_try"] == "5000000.00"
    assert block["net_excl_financing_try"] == "1000000.00"      # profit = 6M − 5M
    assert block["efektif_arsa_maliyeti_try"] == "2000000.00"   # 5M × 4/10
    assert block["landowner_share_pct"] == "40.00"
    # Planned split: all 6 sellable sold, none remaining; 4 are the landowner's.
    split = block["planned_split"]
    assert split["contractor"]["units"] == 6 and split["sold"]["units"] == 6
    assert split["remaining"]["units"] == 0 and split["landowner"]["units"] == 4


# --------------------------------------------------------------------------- #
# §0 — correctness is DATA-DRIVEN, not deal_structure-driven
# --------------------------------------------------------------------------- #
def test_deal_structure_does_not_change_the_numbers(db, seed):
    # A deliberately "wrong" deal_structure must not move revenue/cost — the P&L
    # follows the recorded amounts (sale owner_side, cash, costs), never the enum.
    p = _sellside(db, seed)
    _sale(db, p, "5000000", owner="yuklenici")
    _sale(db, p, "3000000", owner="arsa_sahibi")
    _landowner(db, p, "1000000")
    _cost(db, p, "2000000")
    db.commit()
    baseline = sales_service.revenue_cost_totals(db, p, today=TODAY)

    for ds in ("yap_sat_kendi_arsa", "kentsel_donusum", "diger", None):
        p.deal_structure = ds
        db.add(p)
        db.commit()
        rc = sales_service.revenue_cost_totals(db, p, today=TODAY)
        assert rc["revenue_try"] == baseline["revenue_try"] == D("6000000")
        assert rc["cost_try"] == baseline["cost_try"] == D("2000000")


# --------------------------------------------------------------------------- #
# §5 — cashflow consistent after the switch removal; P&L revenue ↔ cash-in
# --------------------------------------------------------------------------- #
def test_cashflow_matches_operator_revenue_yuklenici_plus_cash(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "5000000", date(2025, 6, 1), owner="yuklenici")
    _sale(db, p, "3000000", date(2025, 5, 1), owner="arsa_sahibi")   # excluded from cash-in
    _landowner(db, p, "1000000", date(2025, 4, 1))                   # cash-in
    db.commit()

    rc = sales_service.revenue_cost_totals(db, p, today=TODAY)
    inflows = fin.cashflow_inflows(db, p, today=TODAY)
    cash_in = sum(D(i["net_due_try"]) for i in inflows)
    # The operator revenue and the cash-in lane agree (both = yuklenici sales + cash),
    # and the arsa_sahibi sale appears in NEITHER.
    assert cash_in == D("6000000")
    assert D(rc["revenue_try"]) == cash_in


def test_irr_roi_series_reads_the_same_operator_lane(db, seed):
    # §4 "one selector": the dated IRR/ROI series (cashflow_series → investment_return)
    # must read the SAME operator lane — only the contractor's own (yuklenici) sales +
    # landowner cash. An arsa_sahibi sale must NOT leak in as a positive inflow, or the
    # investment-return block would contradict the operator revenue.
    p = _sellside(db, seed)
    _sale(db, p, "5000000", date(2025, 6, 1), owner="yuklenici")
    _sale(db, p, "3000000", date(2025, 5, 1), owner="arsa_sahibi")   # the landowner's flat
    _landowner(db, p, "1000000", date(2025, 4, 1))
    _cost(db, p, "2000000", d=date(2025, 3, 1))
    db.commit()

    try_flows, _ = sales_service.cashflow_series(db, p)
    positive_in = sum(a for _, a in try_flows if a > 0)
    assert positive_in == D("6000000")      # 5M yuklenici + 1M cash; NOT the 3M arsa_sahibi
    # ROI net profit uses the operator revenue (6M) − cost (2M) — consistent, no leak.
    inv = sales_service.investment_return(db, p, today=TODAY)
    assert inv["net_profit_try"] == "4000000.00"


def test_premade_invoice_report_units_reconcile_with_yuklenici_kpi(db, seed):
    # The premade Hakediş report's per-daire detail table lists the contractor's OWN
    # (yuklenici) sales only — so it reconciles with the "Birim Satış Geliri (Yüklenici)"
    # KPI. An arsa_sahibi sale must not appear in that operator table.
    from app.services import reports_premade as rp

    p = _sellside(db, seed)
    _sale(db, p, "5000000", owner="yuklenici", label="A-1")
    _sale(db, p, "3000000", owner="arsa_sahibi", label="B-1")
    _cost(db, p, "1000000")
    db.commit()

    base = rp.build_invoice_data(db, p, seed["a"]["company"])
    assert base["mode"] == "sell_side"
    assert [u["label"] for u in base["units"]] == ["A-1"]   # arsa_sahibi B-1 excluded


# --------------------------------------------------------------------------- #
# Schema round-trip: deal_structure + per-unit owner_side via the API
# --------------------------------------------------------------------------- #
def _create_payload(**over):
    base = {
        "name": "KD Projesi", "project_code": "KD1", "project_type": "building_residential",
        "revenue_model": "kat_karsiligi", "client_name": "Arsa Sahibi",
        "deal_structure": "kentsel_donusum", "contractor_share_pct": "55",
        "contract_value_try": "10000000", "original_budget_try": "8000000",
        "start_date": "2025-01-01", "planned_end_date": "2026-01-01",
        "units": [
            {"unit_type": "2+1", "count": 6, "gross_m2_each": "100", "owner_side": "yuklenici"},
            {"unit_type": "2+1", "count": 4, "gross_m2_each": "100", "owner_side": "arsa_sahibi"},
        ],
    }
    base.update(over)
    return base


def test_api_create_and_read_deal_structure_and_owner_side(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_create_payload())
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]

    got = client.get(f"/api/v1/projects/{pid}").json()["data"]
    assert got["deal_structure"] == "kentsel_donusum"
    sides = sorted(u["owner_side"] for u in got["units"])
    assert sides == ["arsa_sahibi", "yuklenici"]

    # Editable later: change the deal structure + the quick share fallback.
    upd = client.put(f"/api/v1/projects/{pid}", json={"deal_structure": "nakit_katki",
                                                      "contractor_share_pct": "70"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["data"]["deal_structure"] == "nakit_katki"
    assert upd.json()["data"]["contractor_share_pct"] == "70.00"


def test_api_rejects_invalid_deal_structure_and_owner_side(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    assert client.post("/api/v1/projects", json=_create_payload(deal_structure="bogus")).status_code == 422
    bad_units = [{"unit_type": "2+1", "count": 1, "gross_m2_each": "100", "owner_side": "bogus"}]
    assert client.post("/api/v1/projects", json=_create_payload(units=bad_units)).status_code == 422
