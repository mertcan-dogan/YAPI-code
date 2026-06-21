"""Sell-side P&L calculations (CR-031): per-unit cost allocation, revenue-model-
aware Project P&L, m² maliyet analizi, kur-etkisi, and IRR/ROI.

PURE + ORM-free (like project_financials.py) so the math is unit-testable without
a database. Exact ``Decimal`` throughout; every division is divide-by-zero
guarded. The service layer (services/sales.py) reads the authoritative cost
rollup + the new income rows and feeds plain dicts in here.

GOVERNING RULE (§0.2): this module READS cost totals; it NEVER writes a cost.
Per-unit cost is an *allocation view*. Revenue is chosen by ``revenue_model`` and
is NEVER summed across both sources.
"""
from datetime import date
from decimal import Decimal

from app.calculations.money import D, money, pct, safe_div

ZERO = Decimal("0")
HUNDRED = Decimal("100")
_DAYS_PER_YEAR = 365.0


# --------------------------------------------------------------------------- #
# CR-031-A — per-unit cost allocation + P&L
# --------------------------------------------------------------------------- #
def allocate_unit_costs(
    units: list[dict], total_cost_try, total_cost_usd,
    project_net_m2=None, project_gross_m2=None,
) -> dict:
    """Allocate the authoritative construction cost across SOLD units by each
    unit's share of the PROJECT's total m² (§1.2):
    ``unit_cost = total_cost × unit_m2 / project_total_m2``.

    The denominator is the PROJECT total (net m² preferred, gross fallback) — NOT
    Σ of the sold units. So when units are still unsold, Σ(per-unit cost) is a
    PROPER subset of the cost (== the total only when the sold units span the
    whole project's m²); a single sale never absorbs 100% of cost. Net basis is
    used when every sold unit has a positive net m² AND the project carries a net
    total; otherwise gross. No remainder is redistributed — each unit gets exactly
    its own m² share. Degenerate input (no units / no project area) → null
    cost/pnl per unit, basis exposed.
    """
    total_try = D(total_cost_try)
    total_usd = D(total_cost_usd)
    net_total = D(project_net_m2) if project_net_m2 is not None else ZERO
    gross_total = D(project_gross_m2) if project_gross_m2 is not None else ZERO

    # One consistent basis: net when every sold unit has net m² AND the project
    # carries a net total to divide by; otherwise the project's gross total.
    if units and net_total > ZERO and all(D(u.get("net_m2")) > ZERO for u in units):
        basis, m2_key, denom = "net", "net_m2", net_total
    else:
        basis, m2_key, denom = "gross", "gross_m2", gross_total

    rows: list[dict] = []
    if not units or denom <= ZERO:
        # Can't allocate (no project area) — null cost/pnl, basis exposed.
        for u in units:
            rows.append({**u, "basis_m2": None, "unit_cost_try": None,
                         "unit_cost_usd": None, "pnl_try": None, "pnl_usd": None,
                         "margin_pct": None})
        return {"basis": basis, "denom_m2": str(money(denom)), "allocations": rows,
                "totals": _sales_totals(rows, basis)}

    for u in units:
        basis_m2 = D(u.get(m2_key))
        share = safe_div(basis_m2, denom)
        unit_cost_try = money(total_try * share)
        unit_cost_usd = money(total_usd * share)

        sale_try = D(u.get("sale_price_try"))
        has_usd = u.get("sale_price_usd") is not None
        sale_usd = D(u.get("sale_price_usd"))
        pnl_try = money(sale_try - unit_cost_try)
        pnl_usd = money(sale_usd - unit_cost_usd) if has_usd else None
        # Margin on USD when available (§1.2), else on TRY. Guarded.
        if has_usd and sale_usd > ZERO:
            margin = pct(safe_div(pnl_usd, sale_usd) * HUNDRED)
        elif sale_try > ZERO:
            margin = pct(safe_div(pnl_try, sale_try) * HUNDRED)
        else:
            margin = None

        rows.append({
            **u,
            "basis_m2": str(money(basis_m2)),
            "unit_cost_try": str(unit_cost_try),
            "unit_cost_usd": str(unit_cost_usd),
            "pnl_try": str(pnl_try),
            "pnl_usd": str(pnl_usd) if pnl_usd is not None else None,
            "margin_pct": str(margin) if margin is not None else None,
        })

    return {"basis": basis, "denom_m2": str(money(denom)), "allocations": rows,
            "totals": _sales_totals(rows, basis)}


def _div_or_none(value, divisor):
    """Quantized value/divisor, or None when value is missing or divisor <= 0
    (every m²/unit/floor KPI is guarded — §3.2)."""
    if value is None:
        return None
    d = D(divisor)
    if d <= ZERO:
        return None
    return str(money(safe_div(D(value), d)))


# --------------------------------------------------------------------------- #
# CR-031-C — revenue-model-aware P&L statement
# --------------------------------------------------------------------------- #
def pnl_statement(
    revenue_try, revenue_usd, cost_try, cost_usd, financing_try, financing_usd
) -> dict:
    """Revenue − Cost (− Financing) net + margins, in TRY & USD (§3.1).

    Financing stays a SEPARABLE overlay (§0.2): both ``net_excl_financing`` and
    ``net_incl_financing`` are exposed; their difference is exactly the financing
    total. Margins are on revenue, divide-by-zero guarded.
    """
    rev_try, rev_usd = D(revenue_try), D(revenue_usd)
    cost_try_d, cost_usd_d = D(cost_try), D(cost_usd)
    fin_try, fin_usd = D(financing_try), D(financing_usd)

    net_excl_try = money(rev_try - cost_try_d)
    net_incl_try = money(rev_try - cost_try_d - fin_try)
    net_excl_usd = money(rev_usd - cost_usd_d)
    net_incl_usd = money(rev_usd - cost_usd_d - fin_usd)

    margin_excl = pct(safe_div(net_excl_try, rev_try) * HUNDRED) if rev_try > ZERO else None
    margin_incl = pct(safe_div(net_incl_try, rev_try) * HUNDRED) if rev_try > ZERO else None

    return {
        "revenue_try": str(money(rev_try)),
        "revenue_usd": str(money(rev_usd)),
        "cost_try": str(money(cost_try_d)),
        "cost_usd": str(money(cost_usd_d)),
        "financing_try": str(money(fin_try)),
        "financing_usd": str(money(fin_usd)),
        "net_excl_financing_try": str(net_excl_try),
        "net_incl_financing_try": str(net_incl_try),
        "net_excl_financing_usd": str(net_excl_usd),
        "net_incl_financing_usd": str(net_incl_usd),
        "margin_pct": str(margin_excl) if margin_excl is not None else None,
        "margin_incl_financing_pct": str(margin_incl) if margin_incl is not None else None,
    }


# --------------------------------------------------------------------------- #
# CR-031-C — m² maliyet analizi (§3.2)
# --------------------------------------------------------------------------- #
def m2_analysis(cost_try, cost_usd, today_rate, *, gross_m2, net_m2, unit_count, floor_count) -> dict:
    """Cost per gross m² / net m² / unit / floor, in TRY, USD and today's-rate TRY
    (= cost_usd × today_rate, the FX-revalued cost). Every figure guarded; null
    when its divisor or the area/unit/rate is absent."""
    cost_try_today = (D(cost_usd) * D(today_rate)) if today_rate is not None else None

    def trio(divisor):
        return {
            "try": _div_or_none(D(cost_try), divisor),
            "usd": _div_or_none(D(cost_usd), divisor),
            "try_today": _div_or_none(cost_try_today, divisor) if cost_try_today is not None else None,
        }

    return {
        "gross_m2": str(money(D(gross_m2))) if gross_m2 is not None else None,
        "net_m2": str(money(D(net_m2))) if net_m2 is not None else None,
        "unit_count": int(unit_count) if unit_count else None,
        "floor_count": int(floor_count) if floor_count else None,
        "per_gross_m2": trio(gross_m2),
        "per_net_m2": trio(net_m2),
        "per_unit": trio(unit_count),
        "per_floor": trio(floor_count),
    }


# --------------------------------------------------------------------------- #
# CR-031-C — kur-etkisi (FX-effect) line (§3.3)
# --------------------------------------------------------------------------- #
def fx_effect(cost_try_original, cost_usd, today_rate) -> dict:
    """Güncel TL − Orijinal TL: the gain/loss from revaluing the USD-snapshotted
    cost at today's rate vs its original TRY (§3.3). DERIVED at read-time — never
    written back to any cost row. Null when no today-rate is available."""
    orig = D(cost_try_original)
    if today_rate is None:
        return {"today_rate": None, "cost_try_original": str(money(orig)),
                "cost_try_today": None, "fx_effect_try": None, "fx_effect_pct": None}
    today_try = money(D(cost_usd) * D(today_rate))
    effect = money(today_try - orig)
    effect_pct = pct(safe_div(effect, orig) * HUNDRED) if orig > ZERO else None
    return {
        "today_rate": str(D(today_rate)),
        "cost_try_original": str(money(orig)),
        "cost_try_today": str(today_try),
        "fx_effect_try": str(effect),
        "fx_effect_pct": str(effect_pct) if effect_pct is not None else None,
    }


# --------------------------------------------------------------------------- #
# CR-031-D — IRR (XIRR over irregular dates) / ROI
# --------------------------------------------------------------------------- #
def _xnpv(rate: float, flows: list[tuple[date, float]], t0: date) -> float:
    """Net present value of dated cash flows at an annual ``rate`` (Actual/365)."""
    return sum(cf / (1.0 + rate) ** ((d - t0).days / _DAYS_PER_YEAR) for d, cf in flows)


def xirr(cashflows: list[tuple]) -> float | None:
    """Internal rate of return over irregular dates (XIRR), as an annual fraction.

    Pure Python (no SciPy). Robust bisection on a bracket found by expanding the
    upper bound until ``xnpv`` changes sign — Newton-free so it never diverges.
    Returns None (never raises) when a root cannot exist: fewer than 2 flows, or
    the amounts don't include BOTH a positive and a negative (no sign change → an
    all-inflow or all-outflow series has no IRR).
    """
    flows = sorted(((d, float(a)) for d, a in cashflows), key=lambda x: x[0])
    amts = [a for _, a in flows]
    if len(flows) < 2 or not (any(a > 0 for a in amts) and any(a < 0 for a in amts)):
        return None
    t0 = flows[0][0]
    f = lambda r: _xnpv(r, flows, t0)  # noqa: E731

    lo, hi = -0.999999, 1.0
    flo, fhi = f(lo), f(hi)
    tries = 0
    while flo * fhi > 0 and hi < 1e7 and tries < 80:
        hi *= 2.0
        fhi = f(hi)
        tries += 1
    if flo * fhi > 0:
        return None  # no bracket → no real root in range
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0


def _irr_pct(cashflows: list[tuple]):
    """XIRR as a 2dp percentage Decimal, or None for a degenerate series."""
    r = xirr(cashflows)
    return pct(D(r) * HUNDRED) if r is not None else None


def investment_return(
    try_flows: list[tuple], usd_flows: list[tuple], *,
    revenue_try, cost_try, start_date, last_date, net_m2=None, unit_count=None,
) -> dict:
    """IRR (TRY & USD) + ROI + duration + m²-başı getiri (§4.1).

    ``*_flows`` are [(date, signed_amount)] — outflows negative (cost), inflows
    positive (sell-side sales+landowner OR hakediş, per revenue_model). IRR is
    null for a degenerate (single-sign) series. ROI = (revenue−cost)/cost; all
    guarded. Duration = whole months start→last cash-flow.
    """
    rev, cost = D(revenue_try), D(cost_try)
    net_profit = money(rev - cost)
    roi_pct = pct(safe_div(net_profit, cost) * HUNDRED) if cost > ZERO else None

    duration_months = None
    if start_date is not None and last_date is not None and last_date >= start_date:
        duration_months = (last_date.year - start_date.year) * 12 + (last_date.month - start_date.month)

    per_net_m2 = str(money(safe_div(net_profit, D(net_m2)))) if net_m2 and D(net_m2) > ZERO else None
    per_unit = str(money(safe_div(net_profit, D(unit_count)))) if unit_count else None

    irr_try = _irr_pct(try_flows)
    irr_usd = _irr_pct(usd_flows)
    return {
        "irr_try_pct": str(irr_try) if irr_try is not None else None,
        "irr_usd_pct": str(irr_usd) if irr_usd is not None else None,
        "roi_pct": str(roi_pct) if roi_pct is not None else None,
        "net_profit_try": str(net_profit),
        "total_cost_try": str(money(cost)),
        "duration_months": duration_months,
        "profit_per_net_m2_try": per_net_m2,
        "profit_per_unit_try": per_unit,
    }


def yearly_cashflow_rows(try_flows: list[tuple], usd_flows: list[tuple]) -> list[dict]:
    """Per-year inflow/outflow/net (TRY & USD), mirroring the workbook's IRR feed
    table. Years are taken from the union of both series, ascending."""
    by_year: dict[int, dict] = {}
    for flows, suffix in ((try_flows, "try"), (usd_flows, "usd")):
        for d, amt in flows:
            a = D(amt)
            y = by_year.setdefault(d.year, {"inflow_try": ZERO, "outflow_try": ZERO,
                                            "inflow_usd": ZERO, "outflow_usd": ZERO})
            key = ("inflow_" if a >= ZERO else "outflow_") + suffix
            y[key] += a if a >= ZERO else -a
    rows = []
    for y in sorted(by_year):
        b = by_year[y]
        rows.append({
            "year": y,
            "inflow_try": str(money(b["inflow_try"])),
            "outflow_try": str(money(b["outflow_try"])),
            "net_try": str(money(b["inflow_try"] - b["outflow_try"])),
            "inflow_usd": str(money(b["inflow_usd"])),
            "outflow_usd": str(money(b["outflow_usd"])),
            "net_usd": str(money(b["inflow_usd"] - b["outflow_usd"])),
        })
    return rows


def _sales_totals(rows: list[dict], basis: str) -> dict:
    """Σ sales TRY/USD, count, total m² (basis) and avg price/m² (§1.2)."""
    n = len(rows)
    sum_try = sum((D(r.get("sale_price_try")) for r in rows), ZERO)
    sum_usd = sum((D(r.get("sale_price_usd")) for r in rows
                   if r.get("sale_price_usd") is not None), ZERO)
    sum_cost_try = sum((D(r.get("unit_cost_try")) for r in rows
                        if r.get("unit_cost_try") is not None), ZERO)
    sum_cost_usd = sum((D(r.get("unit_cost_usd")) for r in rows
                        if r.get("unit_cost_usd") is not None), ZERO)
    m2_key = "net_m2" if basis == "net" else "gross_m2"
    sum_m2 = sum((D(r.get(m2_key)) for r in rows), ZERO)
    pnl_try = money(sum_try - sum_cost_try)
    return {
        "count": n,
        "sale_price_try": str(money(sum_try)),
        "sale_price_usd": str(money(sum_usd)),
        "cost_try": str(money(sum_cost_try)),
        "cost_usd": str(money(sum_cost_usd)),
        "pnl_try": str(pnl_try),
        "pnl_usd": str(money(sum_usd - sum_cost_usd)),
        "total_m2": str(money(sum_m2)),
        "avg_price_per_m2_try": str(money(safe_div(sum_try, sum_m2))) if sum_m2 > ZERO else None,
        "margin_pct": str(pct(safe_div(pnl_try, sum_try) * HUNDRED)) if sum_try > ZERO else None,
    }
