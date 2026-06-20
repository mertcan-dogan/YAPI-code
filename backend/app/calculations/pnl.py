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
