"""CR-050 — chronological sort: report rows come back in time order.

The studio engine's ``_sort_rows`` is wired into ``run_spec`` (after ``_build_rows``,
before ``limit``/``HARD_ROW_LIMIT`` truncation). Before CR-050 it defaulted a
*time-series* to first-metric-DESCENDING, so monthly/quarterly rows came out
ordered by amount (group/hash order) — the DGN "Aylık Nakit Akışı" zig-zag: an
Excel/Studio line chart that references the data range plotted months scrambled.

CR-050 makes ``_sort_rows`` default a result that has a date-typed dimension
(month/quarter/year/week) to THAT dimension, ASCENDING (chronological). The
existing string keyfn sorts ``"2018-01"…"2020-12"`` correctly. Non-time tables
keep the first-metric-descending top-N default; an explicit ``sort`` always wins.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.services.studio import engine

D = Decimal
TODAY = date(2026, 6, 30)


def _uid(seed, label="a"):
    return seed[label]["users"][ROLE_DIRECTOR].id


def _cost(db, p, amount, *, uid, d, cat="material_steel"):
    amt = D(str(amount))
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category=cat,
        amount_try=amt, vat_amount_try=D("0"), total_with_vat_try=amt,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.flush()


def _set_span(db, p, start, end):
    p.start_date = start
    p.planned_end_date = end
    db.add(p)
    db.flush()


def _run(db, cid, spec):
    return engine.run_spec(db, cid, spec, today=TODAY)


# Amounts chosen so amount-DESC order != chronological order — the only way a green
# test proves the engine sorts by DATE, not by coincidence.  month -> amount:
#   2018-01:40k  2018-06:10k  2019-09:50k  2020-03:30k  2020-12:20k
# chronological: 2018-01, 2018-06, 2019-09, 2020-03, 2020-12
# amount-desc  : 2019-09, 2018-01, 2020-03, 2020-12, 2018-06  (the OLD default)
_MULTIYEAR = [
    (date(2018, 1, 15), "40000"),
    (date(2018, 6, 15), "10000"),
    (date(2019, 9, 20), "50000"),
    (date(2020, 3, 5), "30000"),
    (date(2020, 12, 28), "20000"),
]
_CHRONO = ["2018-01", "2018-06", "2019-09", "2020-03", "2020-12"]
_AMOUNT_DESC = ["2019-09", "2018-01", "2020-03", "2020-12", "2018-06"]


def _seed_multiyear(db, p, uid):
    for d, amt in _MULTIYEAR:
        _cost(db, p, amt, uid=uid, d=d)
    db.commit()


# --------------------------------------------------------------------------- #
# 1 — no sort + a date dim → ascending (chronological), full span in order
# --------------------------------------------------------------------------- #
def test_no_sort_month_dim_is_chronological_ascending(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"]})
    months = [r["dims"]["month"] for r in res["rows"]]
    assert months == _CHRONO                 # ascending, spans 2018-01 … 2020-12
    assert months == sorted(months)
    assert months != _AMOUNT_DESC            # proves DATE order, not the old amount order


def test_quarter_and_year_default_chronological(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    q = [r["dims"]["quarter"] for r in
         _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["quarter"]})["rows"]]
    assert q == ["2018-Q1", "2018-Q2", "2019-Q3", "2020-Q1", "2020-Q4"]
    assert q == sorted(q)
    y = [r["dims"]["year"] for r in
         _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["year"]})["rows"]]
    assert y == ["2018", "2019", "2020"]


def test_week_dim_defaults_chronological(db, seed):
    # 'week' is also type=='date'; its "YYYY-Www" key is lexical == chronological.
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "40000", uid=uid, d=date(2018, 3, 15))
    _cost(db, p, "50000", uid=uid, d=date(2019, 8, 20))   # largest amount, middle date
    _cost(db, p, "30000", uid=uid, d=date(2020, 1, 10))
    db.commit()
    weeks = [r["dims"]["week"] for r in
             _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["week"]})["rows"]]
    assert len(weeks) == 3 and all("-W" in w for w in weeks)
    assert weeks == sorted(weeks)             # chronological
    assert weeks[0].startswith("2018")        # earliest date first, NOT the largest amount (2019)


def test_date_dim_wins_default_even_when_not_first(db, seed):
    # dimensions=[cost_category, month], no sort → the date dim is the chronological
    # default key even though it is the 2nd dim; the month column is non-decreasing.
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "10000", uid=uid, d=date(2020, 5, 1), cat="material_steel")
    _cost(db, p, "90000", uid=uid, d=date(2018, 2, 1), cat="labour_direct")
    _cost(db, p, "20000", uid=uid, d=date(2019, 7, 1), cat="material_steel")
    db.commit()
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["cost_category", "month"]})
    months = [r["dims"]["month"] for r in res["rows"]]
    assert months == sorted(months)          # chronological by the date dim
    assert months == ["2018-02", "2019-07", "2020-05"]


# --------------------------------------------------------------------------- #
# 2 — an explicit sort always wins (metric or dim, asc or desc)
# --------------------------------------------------------------------------- #
def test_explicit_metric_sort_desc_overrides_chronological(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"],
                                  "sort": {"by": "cost_try", "dir": "desc"}})
    months = [r["dims"]["month"] for r in res["rows"]]
    vals = [r["metrics"]["cost_try"] for r in res["rows"]]
    assert months == _AMOUNT_DESC            # explicit metric-desc beats the chrono default
    assert vals == sorted(vals, reverse=True)


def test_explicit_dim_sort_desc_is_reverse_chronological(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"],
                                  "sort": {"by": "month", "dir": "desc"}})
    months = [r["dims"]["month"] for r in res["rows"]]
    assert months == list(reversed(_CHRONO))


def test_explicit_metric_sort_asc(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"],
                                  "sort": {"by": "cost_try", "dir": "asc"}})
    vals = [r["metrics"]["cost_try"] for r in res["rows"]]
    assert vals == [10000.0, 20000.0, 30000.0, 40000.0, 50000.0]


# --------------------------------------------------------------------------- #
# 3 — non-time table keeps the first-metric-DESC top-N default
# --------------------------------------------------------------------------- #
def test_non_time_table_defaults_to_first_metric_desc(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _cost(db, p, "100000", uid=uid, d=date(2026, 1, 10), cat="material_steel")
    _cost(db, p, "30000", uid=uid, d=date(2026, 1, 10), cat="labour_direct")
    _cost(db, p, "70000", uid=uid, d=date(2026, 1, 10), cat="material_concrete")
    db.commit()
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["cost_category"]})
    vals = [r["metrics"]["cost_try"] for r in res["rows"]]
    assert vals == [100000.0, 70000.0, 30000.0]   # first metric, descending (ranking intact)


# --------------------------------------------------------------------------- #
# 4 — limit applies AFTER the sort → a deterministic, sorted top-N (not arbitrary)
# --------------------------------------------------------------------------- #
def test_limit_after_chronological_sort_returns_earliest_n(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"], "limit": 3})
    months = [r["dims"]["month"] for r in res["rows"]]
    assert res["meta"]["truncated"] is True
    assert months == _CHRONO[:3]              # the earliest 3 months, in order (not arbitrary)


def test_limit_after_explicit_metric_sort_is_top_n_by_amount(db, seed):
    p = seed["a"]["project"]
    _seed_multiyear(db, p, _uid(seed))
    res = _run(db, p.company_id, {"metrics": ["cost_try"], "dimensions": ["month"],
                                  "sort": {"by": "cost_try", "dir": "desc"}, "limit": 2})
    vals = [r["metrics"]["cost_try"] for r in res["rows"]]
    assert vals == [50000.0, 40000.0]         # genuine top-2 by amount


# --------------------------------------------------------------------------- #
# 5 — the DGN repro: monthly CASH results come back chronological so the CR-046
#     line/bar charts (which reference the data range) plot left → right in time.
# --------------------------------------------------------------------------- #
def test_cash_grain_monthly_is_chronological_dgn_repro(db, seed):
    p = seed["a"]["project"]
    uid = _uid(seed)
    _set_span(db, p, date(2018, 1, 1), date(2020, 12, 31))
    _cost(db, p, "300000", uid=uid, d=date(2018, 6, 15))
    _cost(db, p, "500000", uid=uid, d=date(2020, 3, 5))
    _cost(db, p, "100000", uid=uid, d=date(2019, 9, 20))
    db.commit()
    # no sort, no date_range → all-time monthly cash across the real 2018–2020 life
    res = _run(db, p.company_id, {"metrics": ["cash_out", "cum_cash"], "dimensions": ["month"]})
    months = [r["dims"]["month"] for r in res["rows"]]
    assert months == sorted(months)                       # chronological, no zig-zag
    assert {"2018-06", "2019-09", "2020-03"} <= set(months)
    # the data months appear in increasing position (so the cumulative line reads l→r)
    assert months.index("2018-06") < months.index("2019-09") < months.index("2020-03")
