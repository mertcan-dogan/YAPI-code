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


# --------------------------------------------------------------------------- #
# CR-031-A — per-unit cost allocation + P&L
# --------------------------------------------------------------------------- #
def _basis_for(units: list[dict]) -> str:
    """Allocation basis is net m² when EVERY unit has a positive net m²; otherwise
    fall back to gross m² for the whole project (§1.2 — one consistent basis)."""
    if units and all(D(u.get("net_m2")) > ZERO for u in units):
        return "net"
    return "gross"


def allocate_unit_costs(
    units: list[dict], total_cost_try, total_cost_usd
) -> dict:
    """Allocate the authoritative construction cost across sold units by m² share
    (§1.2): ``unit_cost = total_cost × unit_m2 / Σ units_m2``.

    Basis = net m² (gross fallback when any net is missing). The quantized
    per-unit costs sum EXACTLY to the total (the final unit carries the rounding
    remainder), so the split is 100% of cost — never a penny over/under. Returns
    each unit enriched with cost/pnl/margin plus the basis used and a totals row.
    Degenerate input (no units / zero m²) → empty allocations, null totals.
    """
    total_try = D(total_cost_try)
    total_usd = D(total_cost_usd)
    basis = _basis_for(units)
    m2_key = "net_m2" if basis == "net" else "gross_m2"

    denom = sum((D(u.get(m2_key)) for u in units), ZERO)
    rows: list[dict] = []
    if not units or denom <= ZERO:
        # Can't allocate (no area) — return units with null cost/pnl, basis exposed.
        for u in units:
            rows.append({**u, "basis_m2": None, "unit_cost_try": None,
                         "unit_cost_usd": None, "pnl_try": None, "pnl_usd": None,
                         "margin_pct": None})
        return {"basis": basis, "denom_m2": str(money(denom)), "allocations": rows,
                "totals": _sales_totals(rows, basis)}

    n = len(units)
    acc_try = ZERO
    acc_usd = ZERO
    for i, u in enumerate(units):
        basis_m2 = D(u.get(m2_key))
        share = safe_div(basis_m2, denom)
        if i < n - 1:
            unit_cost_try = money(total_try * share)
            unit_cost_usd = money(total_usd * share)
        else:
            # Last unit carries the remainder so Σ == total exactly.
            unit_cost_try = money(total_try - acc_try)
            unit_cost_usd = money(total_usd - acc_usd)
        acc_try += unit_cost_try
        acc_usd += unit_cost_usd

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
