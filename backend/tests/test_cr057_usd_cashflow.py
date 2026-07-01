"""CR-057 — USD-at-date in the cashflow lane + Satışlar export pairing.

Part A (SACRED pure math — ``calculations/cashflow.py``):
  * ``compute_monthly_cashflow`` carries a USD-at-date companion per bucket:
    ``Σ(₺_amount ÷ row.fx_rate_usd)`` (rate-at-date, VAT-inclusive — the USD of the
    real cash). Planned/future months use the planned buckets, past use actual —
    mirroring the ₺ effective selection.
  * A contributing row with a null ``fx_rate_usd`` POISONS that bucket's USD to
    ``None`` (→ "–"), never a partial sum; ``usd_missing`` counts it. A zero-amount
    flow never poisons (its USD is 0 regardless of rate).
  * The cumulative USD poisons to ``None`` once any month in its running total is
    ``None``; ``opening_balance_usd`` seeds the windowed cumulative (None if a
    pre-window month is unrated).
  * The ₺ output is BYTE-IDENTICAL whether or not a row carries a rate (USD is
    additive-only).

Part B (engine — ``studio/engine.py``):
  * ``_resolve_cash_groups`` returns cash_in/out/net/cum in USD under ``basis=usd``
    (a poisoned month → ``None`` → "–"); ₺ is unchanged. ``run_spec_usd`` no longer
    nulls the cash metrics, and ``meta.usd_missing_count`` surfaces unratable months.
"""
from datetime import date
from decimal import Decimal

from app.calculations import compute_monthly_cashflow
from app.calculations.cashflow import opening_balance_usd
from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.services.studio import engine

D = Decimal
TODAY = date(2025, 6, 15)   # Jan–May 2025 are past; Sep 2025 is future


def _cost(twv, *, entry=None, due=None, status="paid", rate=None):
    """A minimal cashflow cost-row dict (the shape ``compute_monthly_cashflow`` reads)."""
    return {
        "total_with_vat_try": D(twv),
        "entry_date": entry,
        "payment_due_date": due,
        "payment_status": status,
        "fx_rate_usd": D(rate) if rate is not None else None,
    }


def _invoice(amt_received=None, *, recv=None, net_due=None, due=None, status="paid", rate=None):
    return {
        "amount_received_try": D(amt_received) if amt_received is not None else D("0"),
        "net_due_try": D(net_due) if net_due is not None else D("0"),
        "date_received": recv,
        "due_date": due,
        "payment_status": status,
        "fx_rate_usd": D(rate) if rate is not None else None,
    }


def _by_month(rows):
    return {r["month"]: r for r in rows}


# --------------------------------------------------------------------------- #
# Part A — USD-at-date = Σ(₺ ÷ rate)
# --------------------------------------------------------------------------- #
def test_actual_out_usd_is_sum_of_try_over_rate():
    costs = [_cost("100000", entry=date(2025, 1, 5), rate="40"),   # 2500
             _cost("60000", entry=date(2025, 1, 20), rate="30")]   # 2000
    jan = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))["2025-01"]
    assert jan["actual_out_usd"] == D("4500.00")
    assert jan["actual_out_try"] == D("160000.00")
    assert jan["net_usd"] == D("-4500.00")            # past month, no inflow


def test_actual_in_usd():
    invs = [_invoice("120000", recv=date(2025, 2, 10), rate="40")]  # 3000
    feb = _by_month(compute_monthly_cashflow([], invs, today=TODAY))["2025-02"]
    assert feb["actual_in_usd"] == D("3000.00")
    assert feb["net_usd"] == D("3000.00")


def test_future_month_uses_planned_usd():
    # A future-dated unpaid cost → planned bucket; USD comes from the planned side.
    costs = [_cost("100000", due=date(2025, 9, 1), status="unpaid", rate="40")]
    sep = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))["2025-09"]
    assert sep["is_past"] is False and sep["is_current"] is False
    assert sep["planned_out_usd"] == D("2500.00")
    assert sep["net_usd"] == D("-2500.00")            # future → planned drives net


# --------------------------------------------------------------------------- #
# Part A — poisoning: a null rate → None, never a partial sum
# --------------------------------------------------------------------------- #
def test_null_rate_poisons_bucket_and_counts_missing():
    costs = [_cost("100000", entry=date(2025, 1, 5), rate="40"),    # would be 2500
             _cost("60000", entry=date(2025, 1, 20), rate=None)]    # no rate → poison
    jan = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))["2025-01"]
    assert jan["actual_out_usd"] is None              # NOT a partial 2500.00
    assert jan["net_usd"] is None
    assert jan["usd_missing"] == 1
    assert jan["actual_out_try"] == D("160000.00")    # ₺ unaffected


def test_usd_missing_counts_every_unrated_row_order_independent():
    # Two unrated non-zero rows in the same month/bucket → usd_missing == 2 (honest
    # per-row count), and the bucket is poisoned regardless of interleaving order.
    forward = [_cost("1000", entry=date(2025, 3, 5), rate="40"),
               _cost("2000", entry=date(2025, 3, 10), rate=None),
               _cost("3000", entry=date(2025, 3, 20), rate=None)]
    reverse = [_cost("2000", entry=date(2025, 3, 10), rate=None),
               _cost("1000", entry=date(2025, 3, 5), rate="40"),
               _cost("3000", entry=date(2025, 3, 20), rate=None)]
    for costs in (forward, reverse):
        mar = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))["2025-03"]
        assert mar["actual_out_usd"] is None      # poisoned either way (never partial)
        assert mar["usd_missing"] == 2            # both unrated rows counted


def test_zero_amount_null_rate_does_not_poison():
    costs = [_cost("100000", entry=date(2025, 1, 5), rate="40"),
             _cost("0", entry=date(2025, 1, 20), rate=None)]        # 0 ₺ → contributes 0 USD
    jan = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))["2025-01"]
    assert jan["actual_out_usd"] == D("2500.00")      # the 0-amount unrated row didn't poison
    assert jan["usd_missing"] == 0


# --------------------------------------------------------------------------- #
# Part A — cumulative USD + opening balance
# --------------------------------------------------------------------------- #
def test_cumulative_usd_running_total():
    costs = [_cost("40000", entry=date(2025, 3, 1), rate="40"),     # -1000
             _cost("20000", entry=date(2025, 4, 1), rate="40")]     # -500
    invs = [_invoice("100000", recv=date(2025, 4, 15), rate="40")]  # +2500
    rows = _by_month(compute_monthly_cashflow(costs, invs, today=TODAY))
    assert rows["2025-03"]["net_usd"] == D("-1000.00")
    assert rows["2025-03"]["cumulative_usd"] == D("-1000.00")
    assert rows["2025-04"]["net_usd"] == D("2000.00")              # 2500 - 500
    assert rows["2025-04"]["cumulative_usd"] == D("1000.00")       # -1000 + 2000


def test_cumulative_usd_poisons_after_a_missing_month():
    costs = [_cost("40000", entry=date(2025, 3, 1), rate=None),     # Mar unrated
             _cost("20000", entry=date(2025, 4, 1), rate="40")]     # Apr rated
    rows = _by_month(compute_monthly_cashflow(costs, [], today=TODAY))
    assert rows["2025-03"]["net_usd"] is None
    assert rows["2025-03"]["cumulative_usd"] is None
    assert rows["2025-04"]["net_usd"] == D("-500.00")             # Apr's own net IS known
    assert rows["2025-04"]["cumulative_usd"] is None              # but the cumulative can't recover


def test_opening_balance_usd_seeds_windowed_cumulative():
    costs = [_cost("40000", entry=date(2025, 1, 1), rate="40"),     # before window: -1000
             _cost("20000", entry=date(2025, 3, 1), rate="40")]     # in window: -500
    assert opening_balance_usd(costs, [], "2025-02", today=TODAY) == D("-1000.00")
    rows = _by_month(compute_monthly_cashflow(
        costs, [], today=TODAY, from_month="2025-02", to_month="2025-04"))
    assert rows["2025-02"]["cumulative_usd"] == D("-1000.00")     # seeded, no activity
    assert rows["2025-03"]["cumulative_usd"] == D("-1500.00")     # -1000 + (-500)


def test_opening_balance_usd_none_when_pre_window_month_unrated():
    costs = [_cost("40000", entry=date(2025, 1, 1), rate=None)]     # unrated, before window
    assert opening_balance_usd(costs, [], "2025-02", today=TODAY) is None


# --------------------------------------------------------------------------- #
# Part A — SACRED: ₺ output byte-identical whether or not a row carries a rate
# --------------------------------------------------------------------------- #
_TRY_KEYS = ["month", "year", "month_num", "planned_out_try", "actual_out_try",
             "planned_in_try", "actual_in_try", "net_try", "cumulative_try",
             "is_past", "is_current"]


def test_try_output_byte_identical_with_and_without_rate():
    costs = [_cost("40000", entry=date(2025, 3, 1), due=date(2025, 5, 1), status="unpaid", rate="40"),
             _cost("20000", entry=date(2025, 4, 1), rate="30")]
    invs = [_invoice("100000", recv=date(2025, 4, 15), rate="40"),
            _invoice(net_due="50000", due=date(2025, 9, 1), status="unpaid", rate="25")]
    rated = compute_monthly_cashflow(costs, invs, today=TODAY)
    # Strip every rate → the ₺ math must be identical (USD is additive-only).
    bare_costs = [{k: v for k, v in c.items() if k != "fx_rate_usd"} for c in costs]
    bare_invs = [{k: v for k, v in i.items() if k != "fx_rate_usd"} for i in invs]
    bare = compute_monthly_cashflow(bare_costs, bare_invs, today=TODAY)
    assert len(rated) == len(bare)
    for r, b in zip(rated, bare):
        for k in _TRY_KEYS:
            assert r[k] == b[k], f"₺ field {k} diverged: {r[k]} != {b[k]}"


# --------------------------------------------------------------------------- #
# Part B — engine exposes cash USD under basis=usd
# --------------------------------------------------------------------------- #
def _login(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])
    return seed[label]["project"], seed[label]["users"][ROLE_DIRECTOR].id


def _rated_cost(db, p, uid, amount_try, rate, d=date(2025, 1, 10)):
    at = D(str(amount_try))
    r = D(str(rate)) if rate is not None else None
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category="material_steel",
        amount_try=at, vat_amount_try=D("0"), total_with_vat_try=at,
        amount_usd=None, fx_rate_usd=r,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.commit()


def test_engine_cash_out_usd_under_basis_usd(client, db, seed):
    p, uid = _login(client, seed)
    _rated_cost(db, p, uid, "100000", "40")   # 100000 / 40 = 2500 USD outflow
    spec = {"metrics": ["cash_out", "net_cash"], "dimensions": ["month"],
            "basis": {"currency": "usd"}}
    res = engine.run_spec(db, p.company_id, spec, today=TODAY)
    months = {r["dims"]["month"]: r["metrics"] for r in res["rows"]}
    assert round(float(months["2025-01"]["cash_out"]), 2) == 2500.0
    assert round(float(months["2025-01"]["net_cash"]), 2) == -2500.0
    assert round(float(res["totals"]["metrics"]["cash_out"]), 2) == 2500.0


def test_engine_cash_try_basis_unchanged(client, db, seed):
    p, uid = _login(client, seed)
    _rated_cost(db, p, uid, "100000", "40")
    res = engine.run_spec(db, p.company_id, {"metrics": ["cash_out"], "dimensions": ["month"]},
                          today=TODAY)   # default TRY basis
    assert round(float(res["totals"]["metrics"]["cash_out"]), 2) == 100000.0


def test_engine_cum_cash_usd(client, db, seed):
    p, uid = _login(client, seed)
    _rated_cost(db, p, uid, "40000", "40", d=date(2025, 1, 10))   # -1000
    _rated_cost(db, p, uid, "20000", "40", d=date(2025, 2, 10))   # -500
    res = engine.run_spec(db, p.company_id,
                          {"metrics": ["cum_cash"], "dimensions": ["month"],
                           "basis": {"currency": "usd"}}, today=TODAY)
    months = {r["dims"]["month"]: r["metrics"]["cum_cash"] for r in res["rows"]}
    assert round(float(months["2025-01"]), 2) == -1000.0
    assert round(float(months["2025-02"]), 2) == -1500.0


def test_run_spec_usd_cash_missing_rate_month_is_dash_and_counted(client, db, seed):
    from app.services.studio.engine import run_spec_usd
    p, uid = _login(client, seed)
    _rated_cost(db, p, uid, "100000", "40", d=date(2025, 1, 10))   # rated → real USD
    _rated_cost(db, p, uid, "50000", None, d=date(2025, 2, 10))    # unrated → Feb "–"
    res = run_spec_usd(db, p.company_id, {"metrics": ["cash_out"], "dimensions": ["month"]},
                       today=TODAY)
    months = {r["dims"]["month"]: r["metrics"]["cash_out"] for r in res["rows"]}
    assert round(float(months["2025-01"]), 2) == 2500.0            # rated month: real USD
    assert months["2025-02"] is None                               # unrated month: "–", not partial
    assert res["meta"]["usd_missing_count"] >= 1                   # surfaced for the footnote


def test_run_spec_usd_pairs_try_and_usd_cash(client, db, seed):
    # The companion pairs column-for-column: ₺ run shows ₺, USD run shows real USD.
    from app.services.studio.engine import run_both_currencies
    p, uid = _login(client, seed)
    _rated_cost(db, p, uid, "100000", "40")
    t, u = run_both_currencies(db, p.company_id,
                               {"metrics": ["cash_out"], "dimensions": ["month"]}, today=TODAY)
    assert round(float(t["totals"]["metrics"]["cash_out"]), 2) == 100000.0   # ₺
    assert round(float(u["totals"]["metrics"]["cash_out"]), 2) == 2500.0     # USD-at-date
