"""Sell-side revenue loaders + rollups (CR-031).

Loads the new ``unit_sales`` (CR-031-A) / ``landowner_payments`` (CR-031-B) rows
and reads the authoritative cost rollup (CR-007/014) to drive per-unit cost
allocation + P&L. READ-ONLY over cost: it never writes a cost_entry, never
mutates budget/forecast/margin internals (§0.2).
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations import pnl as pnl_calc
from app.calculations.money import D, money
from app.models.project import Project
from app.models.unit_sale import UnitSale


# --------------------------------------------------------------------------- #
# Authoritative cost totals (READ-ONLY view of the CR-007/014 rollup)
# --------------------------------------------------------------------------- #
def construction_cost_totals(db: Session, project: Project, today: date | None = None) -> dict:
    """The project's authoritative construction cost in TRY & USD, read from the
    existing rollups — the basis for per-unit allocation + the P&L cost line.

    TRY = ``forecast_final_cost_try`` (the headline final-cost figure shown
    everywhere). USD = the SUM of per-row ``amount_usd`` snapshots (CR-014-C,
    point-in-time). Both are pure reads; neither is recomputed or written back.
    """
    from app.services import financials as fin_service

    f = fin_service.project_financials(db, project, today=today)
    usd = fin_service.project_usd_totals(db, project)
    return {
        "total_try": money(f["forecast_final_cost_try"]),
        "total_usd": money(D(usd["costs"]["amount_usd"])),
        "usd_missing_count": usd["costs"]["usd_missing_count"],
    }


# --------------------------------------------------------------------------- #
# CR-031-A — unit sales + per-unit P&L
# --------------------------------------------------------------------------- #
def list_unit_sales(db: Session, project: Project) -> list[UnitSale]:
    return db.execute(
        select(UnitSale)
        .where(UnitSale.project_id == project.id, UnitSale.is_deleted.is_(False))
        .order_by(UnitSale.sale_date.desc(), UnitSale.created_at.desc())
    ).scalars().all()


def _s(v):
    """Stringify a Decimal money/area value (None-safe) for a JSON-safe payload."""
    return str(v) if v is not None else None


def _sale_dict(s: UnitSale) -> dict:
    # NOTE: gross_m2/net_m2/sale_price_* stay numeric strings so the pure
    # allocation engine (D(...)) and the JSON payload both see exact values.
    return {
        "id": str(s.id),
        "project_unit_id": str(s.project_unit_id) if s.project_unit_id else None,
        "unit_label": s.unit_label,
        "unit_type": s.unit_type,
        "floor": s.floor,
        "gross_m2": _s(s.gross_m2),
        "net_m2": _s(s.net_m2),
        "buyer_name": s.buyer_name,
        "sale_price_try": _s(s.sale_price_try),
        "sale_price_usd": _s(s.sale_price_usd),
        "sale_date": s.sale_date.isoformat() if s.sale_date else None,
        "fx_rate_usd": _s(s.fx_rate_usd),
        "payment_type": s.payment_type,
        "installment_note": s.installment_note,
        "deed_status": s.deed_status,
        "deed_date": s.deed_date.isoformat() if s.deed_date else None,
        "owner_side": s.owner_side,
        "notes": s.notes,
    }


def unit_sales_pnl(db: Session, project: Project, today: date | None = None) -> dict:
    """Per-unit cost allocation + P&L over the project's unit sales (§1.2).

    Reads the authoritative construction cost, allocates it across sold units by
    m² share, returns each sale enriched with cost/pnl/margin + a totals row and
    the basis used (net / gross). Empty sales → empty allocations, zeroed totals.
    """
    sales = list_unit_sales(db, project)
    costs = construction_cost_totals(db, project, today=today)
    units = [_sale_dict(s) for s in sales]
    result = pnl_calc.allocate_unit_costs(units, costs["total_try"], costs["total_usd"])
    result["cost_total_try"] = str(costs["total_try"])
    result["cost_total_usd"] = str(costs["total_usd"])
    result["usd_missing_count"] = costs["usd_missing_count"]
    return result
