"""CR-051 — revenue-model-aware cash INFLOWS (sell-side Nakit Akışı).

The cash-in lane used to come from ``client_invoices`` for EVERY revenue model, so
a sell-side (kat karşılığı / yap-sat / hasılat paylaşımı) project's Nakit Akışı was
wrong: hakediş invoices leaked into cash-in, and a clean sell-side project — whose
money lives in ``unit_sales`` + ``landowner_payments`` — got an empty/wrong
cashflow. CR-051 routes inflows through ``financials.cashflow_inflows`` (model-aware,
mirroring ``sales.revenue_cost_totals``). The pure ``calculations/cashflow.py`` is
untouched. These tests prove the cash timing is right and nothing regresses.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.landowner_payment import LandownerPayment
from app.models.unit_sale import UnitSale
from app.models.user import User
from app.services import financials as fin
from app.services import reports_premade as rp
from app.services.studio import engine

D = Decimal
TODAY = date(2026, 6, 30)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _uid(db, p):
    return db.execute(select(User.id).where(User.company_id == p.company_id)).scalars().first()


def _sellside(db, seed, model="kat_karsiligi", label="a"):
    p = seed[label]["project"]
    p.revenue_model = model
    db.add(p)
    db.flush()
    return p


def _hakedis(db, seed, label="a"):
    p = seed[label]["project"]
    p.revenue_model = "hakedis"
    db.add(p)
    db.flush()
    return p


def _sale(db, p, amount, d, *, label="Daire", owner="yuklenici"):
    db.add(UnitSale(project_id=p.id, company_id=p.company_id, unit_label=label,
                    sale_price_try=D(str(amount)), sale_date=d, owner_side=owner))
    db.flush()


def _landowner(db, p, amount, d):
    db.add(LandownerPayment(project_id=p.id, company_id=p.company_id, payer_name="Arsa Sahibi",
                            payment_date=d, amount_try=D(str(amount))))
    db.flush()


def _cost(db, p, amount, d):
    amt = D(str(amount))
    db.add(CostEntry(project_id=p.id, company_id=p.company_id, entry_date=d,
                     cost_category="material_steel", amount_try=amt, vat_amount_try=D("0"),
                     total_with_vat_try=amt, amount_paid_try=D("0"), payment_status="unpaid",
                     entry_type="actual", created_by=_uid(db, p)))
    db.flush()


def _invoice(db, p, amount, d, *, received=None, recv_date=None, itype="hakedis"):
    """A client invoice that — for a sell-side project — must NOT reach cash-in."""
    amt = D(str(amount))
    db.add(ClientInvoice(
        project_id=p.id, company_id=p.company_id, invoice_number=f"INV-{p.project_code}-{amount}",
        invoice_date=d, invoice_type=itype, amount_try=amt, vat_amount_try=D("0"),
        total_with_vat_try=amt, net_due_try=amt,
        amount_received_try=D(str(received)) if received is not None else D("0"),
        date_received=recv_date, due_date=d, payment_status="paid" if received else "unpaid",
        created_by=_uid(db, p),
    ))
    db.flush()


def _window(p, frm, to, today=TODAY, db=None):
    return fin.project_cashflow_window(db, p, from_month=frm, to_month=to, today=today)["rows"]


def _sum_in(rows):
    """Effective cash-in across rows (actual for past/current, planned for future)."""
    total = D(0)
    for r in rows:
        past = r["is_past"] or r["is_current"]
        total += D(r["actual_in_try"]) if past else D(r["planned_in_try"])
    return total


# --------------------------------------------------------------------------- #
# The adapter itself
# --------------------------------------------------------------------------- #
def test_inflows_sellside_from_sales_and_landowner_not_invoices(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "5800000", date(2020, 12, 1))
    _landowner(db, p, "500000", date(2020, 3, 1))
    _invoice(db, p, "147000", date(2020, 9, 1), received="147000", recv_date=date(2020, 9, 1))
    db.commit()

    inflows = fin.cashflow_inflows(db, p, today=TODAY)
    # Two inflow dicts — the sale + the landowner payment. NO client invoice.
    amounts = sorted(D(i["net_due_try"]) for i in inflows)
    assert amounts == [D("500000"), D("5800000")]
    dates = sorted(i["due_date"] for i in inflows)
    assert dates == [date(2020, 3, 1), date(2020, 12, 1)]


def test_inflows_hakedis_unchanged_uses_invoices(db, seed):
    p = _hakedis(db, seed)
    _invoice(db, p, "70000", date(2025, 7, 1), received="20000", recv_date=date(2025, 7, 5))
    db.commit()
    inflows = fin.cashflow_inflows(db, p, today=TODAY)
    # The existing client_invoice rows, byte-for-byte (the unchanged hakediş lane).
    _, invoices, _ = fin.load_project_inputs(db, p)
    assert inflows == invoices
    assert len(inflows) == 1 and D(inflows[0]["amount_received_try"]) == D("20000")


def test_inflows_excludes_arsa_sahibi_sales_includes_landowner(db, seed):
    # CR-053 supersedes CR-051's LANDOWNER_PAYMENTS_AS_CASH switch with the per-project
    # operator model. Cash-in = the contractor's OWN (yuklenici) sales + landowner CASH
    # contributions. An arsa_sahibi sale is the landowner's money → it must NOT appear.
    p = _sellside(db, seed)
    _sale(db, p, "5800000", date(2020, 12, 1))                       # yuklenici (default)
    _sale(db, p, "3000000", date(2020, 11, 1), owner="arsa_sahibi")  # landowner's flat — excluded
    _landowner(db, p, "500000", date(2020, 3, 1))                    # cash contribution → always in
    db.commit()
    inflows = fin.cashflow_inflows(db, p, today=TODAY)
    amounts = sorted(D(i["net_due_try"]) for i in inflows)
    assert amounts == [D("500000"), D("5800000")]           # NOT the 3M arsa_sahibi sale
    assert sum(D(i["net_due_try"]) for i in inflows) == D("6300000")


# --------------------------------------------------------------------------- #
# Cashflow rows — sell-side cash-in at sale/payment dates, no invoice leak
# --------------------------------------------------------------------------- #
def test_sellside_cash_in_at_sale_dates_no_hakedis_leak(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "5800000", date(2020, 12, 1))
    _landowner(db, p, "500000", date(2020, 3, 1))
    _cost(db, p, "120000", date(2020, 6, 10))
    # A hakediş invoice WITH cash received in-window — would corrupt cash-in if it leaked.
    _invoice(db, p, "147000", date(2020, 9, 1), received="147000", recv_date=date(2020, 9, 1))
    db.commit()

    rows = {r["month"]: r for r in _window(p, "2020-01", "2020-12", db=db)}
    assert D(rows["2020-03"]["actual_in_try"]) == D("500000")    # landowner cash
    assert D(rows["2020-12"]["actual_in_try"]) == D("5800000")   # sale cash
    assert D(rows["2020-09"]["actual_in_try"]) == D("0")         # hakediş does NOT leak
    assert _sum_in(rows.values()) == D("6300000")               # sales+landowner only
    # Outflow still the cost (unchanged for all models).
    assert D(rows["2020-06"]["actual_out_try"]) == D("120000")


def test_hakedis_cashflow_unchanged(db, seed):
    p = _hakedis(db, seed)
    _invoice(db, p, "300000", date(2025, 3, 1), received="300000", recv_date=date(2025, 3, 1))
    _cost(db, p, "100000", date(2025, 2, 1))
    db.commit()
    rows = {r["month"]: r for r in _window(p, "2025-01", "2025-06", db=db)}
    assert D(rows["2025-03"]["actual_in_try"]) == D("300000")    # invoice cash, as before
    assert D(rows["2025-02"]["actual_out_try"]) == D("100000")


def test_future_dated_sale_shows_as_planned(db, seed):
    # A sale dated AFTER today must still be visible — as a PLANNED inflow (so the
    # net/cumulative include it), mirroring an unpaid invoice.
    p = _sellside(db, seed)
    _sale(db, p, "2000000", date(2026, 9, 1))   # future relative to TODAY (2026-06-30)
    db.commit()
    rows = {r["month"]: r for r in _window(p, "2026-06", "2026-12", db=db)}
    assert D(rows["2026-09"]["planned_in_try"]) == D("2000000")
    assert D(rows["2026-09"]["actual_in_try"]) == D("0")
    assert D(rows["2026-09"]["net_try"]) == D("2000000")        # counts in net


# --------------------------------------------------------------------------- #
# DGN Martı repro — 5,8M sale, NOT 8,92M of mixed invoices
# --------------------------------------------------------------------------- #
def test_dgn_marti_repro_premade_cash_in_is_the_sale(db, seed):
    p = _sellside(db, seed)
    p.name = "DGN Martı"
    db.add(p)
    _sale(db, p, "5800000", date(2020, 12, 1))
    # The mixed client_invoices that USED to drive cash-in (8,92M incl 147K hakediş).
    _invoice(db, p, "4000000", date(2020, 12, 1), received="4000000", recv_date=date(2020, 12, 1), itype="final")
    _invoice(db, p, "1800000", date(2020, 12, 1), received="1800000", recv_date=date(2020, 12, 1), itype="final")
    _invoice(db, p, "2973000", date(2020, 11, 1), received="2973000", recv_date=date(2020, 11, 1), itype="final")
    _invoice(db, p, "147000", date(2020, 9, 1), received="147000", recv_date=date(2020, 9, 1), itype="hakedis")
    db.commit()

    d = rp.build_cashflow_data(db, p, seed["a"]["company"], today=TODAY)
    total_in = sum(p_["in"] for p_ in d["periods"])
    assert total_in == D("5800000")                # the sale — NOT 8,920,000 of invoices
    # The long span (2020-12 → 2025-12) aggregates to quarters, so check the real
    # period keys: the 5,8M sale lands in 2020-Ç4 and the 147K hakediş quarter
    # (2020-Ç3) carries NO inflow — proof the hakediş does not leak.
    by_period = {p_["period"]: p_["in"] for p_ in d["periods"]}
    assert by_period.get("2020-Ç4", D(0)) == D("5800000")
    assert by_period.get("2020-Ç3", D(0)) == D("0")


# --------------------------------------------------------------------------- #
# Span — covers the sales even with NO costs and NO invoices
# --------------------------------------------------------------------------- #
def test_full_span_covers_sales_when_no_invoices(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "3000000", date(2019, 5, 1))   # only a sale; no cost, no invoice
    db.commit()
    lo, hi = fin.cashflow_full_span(db, p, today=TODAY)
    assert lo == "2019-05"                        # span reaches back to the sale month
    # The premade Nakit Akış is NOT empty (sales exist even though invoices don't).
    # The long span (2019→2025 project end) aggregates to quarters, so the 2019 sale
    # lands in a 2019 period and the total cash-in equals the sale.
    periods = rp._cashflow_periods(db, p, TODAY)
    assert periods, "sell-side cashflow must not be empty when only sales exist"
    assert any(pr["period"].startswith("2019") for pr in periods)
    assert sum(pr["in"] for pr in periods) == D("3000000")


def test_full_span_empty_sellside_falls_back(db, seed):
    p = _sellside(db, seed)   # no sales, no landowner, no costs, no invoices
    db.commit()
    periods = rp._cashflow_periods(db, p, TODAY)
    assert periods == []      # genuinely empty → calm note, not a fabricated table


# --------------------------------------------------------------------------- #
# Engine cash grain (studio) — sell-side cash_in from sales, no invoice leak
# --------------------------------------------------------------------------- #
def test_engine_cash_grain_is_model_aware(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "5800000", date(2020, 12, 1))
    _landowner(db, p, "500000", date(2020, 3, 1))
    _invoice(db, p, "147000", date(2020, 9, 1), received="147000", recv_date=date(2020, 9, 1))
    db.commit()

    res = engine.run_spec(db, p.company_id,
                          {"metrics": ["cash_in"], "dimensions": ["month"]}, today=TODAY)
    months = {r["dims"]["month"]: r["metrics"]["cash_in"] for r in res["rows"]}
    assert round(sum(v or 0 for v in months.values()), 2) == 6300000.0   # sales + landowner
    assert round(months.get("2020-12", 0) or 0, 2) == 5800000.0
    assert round(months.get("2020-03", 0) or 0, 2) == 500000.0
    assert round(months.get("2020-09", 0) or 0, 2) == 0.0                # no hakediş leak


# --------------------------------------------------------------------------- #
# No double-count — the P&L / revenue lane is untouched by the cash change
# --------------------------------------------------------------------------- #
def test_no_double_count_pnl_revenue_unaffected(db, seed):
    from app.services import sales as sales_service

    p = _sellside(db, seed)
    _sale(db, p, "5800000", date(2020, 12, 1))
    _landowner(db, p, "500000", date(2020, 3, 1))
    _invoice(db, p, "147000", date(2020, 9, 1), received="147000", recv_date=date(2020, 9, 1))
    db.commit()

    rc = sales_service.revenue_cost_totals(db, p, today=TODAY)
    # Revenue is still sales + landowner (CR-031/047), client invoices explicitly 0 —
    # the cash change did not bleed into revenue, and the sale is counted ONCE.
    assert rc["revenue_source"] == "sales"
    assert rc["revenue_try"] == D("6300000")
    assert rc["revenue_breakdown"]["client_invoices_try"] == "0.00"
    # The cash lane independently sums the SAME sale once (no double-count on cash).
    inflows = fin.cashflow_inflows(db, p, today=TODAY)
    assert sum(D(i["net_due_try"]) for i in inflows) == D("6300000")


# --------------------------------------------------------------------------- #
# Adjacent surfaces kept consistent: 30/60/90 risk cards + per-month drawer
# --------------------------------------------------------------------------- #
def test_cash_need_windows_sellside_uses_future_sales_not_invoices(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "2000000", date(2026, 7, 15))    # future, within 30 days of TODAY
    _invoice(db, p, "900000", date(2026, 7, 10))  # stray hakediş — must NOT leak
    db.commit()
    w30 = next(w for w in fin.cash_need_windows(db, p, today=TODAY) if w["days"] == 30)
    assert w30["expected_in_try"] == "2000000.00"   # the future sale, not the invoice


def test_cash_need_windows_hakedis_unchanged(db, seed):
    p = _hakedis(db, seed)
    _invoice(db, p, "500000", date(2026, 7, 10))  # unpaid invoice due in 30d window
    db.commit()
    w30 = next(w for w in fin.cash_need_windows(db, p, today=TODAY) if w["days"] == 30)
    assert w30["expected_in_try"] == "500000.00"   # outstanding invoice, as before


def test_cashflow_month_detail_sellside_shows_sales_not_invoices(db, seed):
    p = _sellside(db, seed)
    _sale(db, p, "2000000", date(2026, 9, 1))     # future relative to TODAY → expected
    _invoice(db, p, "800000", date(2026, 9, 5))   # stray hakediş — must NOT appear
    db.commit()
    detail = fin.cashflow_month_detail(db, p, "2026-09", today=TODAY)
    assert detail["total_in_try"] == "2000000.00"
    assert len(detail["invoices"]) == 1
    assert detail["invoices"][0]["invoice_number"] is None   # synthetic sell-side row


def test_cashflow_month_detail_hakedis_unchanged(db, seed):
    p = _hakedis(db, seed)
    _invoice(db, p, "800000", date(2026, 9, 5))   # unpaid invoice due in month
    db.commit()
    detail = fin.cashflow_month_detail(db, p, "2026-09", today=TODAY)
    assert detail["total_in_try"] == "800000.00"
    assert detail["invoices"][0]["invoice_number"] is not None  # real invoice row


# --------------------------------------------------------------------------- #
# Footnote — discloses the sell-side cash-in basis (decision-point default)
# --------------------------------------------------------------------------- #
def test_footnote_present_for_sellside_absent_for_hakedis(db, seed):
    sell = _sellside(db, seed, label="a")
    _sale(db, sell, "1000000", date(2025, 5, 1))
    hak = _hakedis(db, seed, label="b")
    _invoice(db, hak, "70000", date(2025, 7, 1))
    db.commit()

    d_sell = rp.build_cashflow_data(db, sell, seed["a"]["company"], today=TODAY)
    d_hak = rp.build_cashflow_data(db, hak, seed["b"]["company"], today=TODAY)
    assert d_sell["footnote"] and "arsa sahibi" in d_sell["footnote"].lower()
    assert d_hak["footnote"] is None
