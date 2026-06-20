"""Sell-side revenue loaders + rollups (CR-031).

Loads the new ``unit_sales`` (CR-031-A) / ``landowner_payments`` (CR-031-B) rows
and reads the authoritative cost rollup (CR-007/014) to drive per-unit cost
allocation + P&L. READ-ONLY over cost: it never writes a cost_entry, never
mutates budget/forecast/margin internals (§0.2).
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calculations import pnl as pnl_calc
from app.calculations.money import D, money, safe_div
from app.models.landowner_payment import LandownerPayment
from app.models.project import Project
from app.models.unit_sale import UnitSale
from app.services import fx


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


def sales_revenue_totals(db: Session, project: Project) -> dict:
    """SQL-side Σ of unit-sales revenue (TRY/USD) + count for a project. Pure
    aggregation (no Python loop) — feeds the revenue-model-aware P&L (CR-031-C)."""
    sum_try, sum_usd, cnt, missing = db.execute(
        select(
            func.coalesce(func.sum(UnitSale.sale_price_try), 0),
            func.coalesce(func.sum(UnitSale.sale_price_usd), 0),
            func.count(UnitSale.id),
            func.coalesce(func.sum(_null_int(UnitSale.sale_price_usd)), 0),
        ).where(UnitSale.project_id == project.id, UnitSale.is_deleted.is_(False))
    ).one()
    return {
        "total_try": money(D(sum_try)),
        "total_usd": money(D(sum_usd)),
        "count": int(cnt),
        "usd_missing_count": int(missing),
    }


# --------------------------------------------------------------------------- #
# CR-031-B — landowner payment ledger
# --------------------------------------------------------------------------- #
def _null_int(col):
    """1 when the column is NULL else 0 — dialect-safe missing-USD counter for a
    SUM (avoids FILTER, unsupported on older SQLite)."""
    from sqlalchemy import case
    return case((col.is_(None), 1), else_=0)


def list_landowner_payments(db: Session, project: Project) -> list[LandownerPayment]:
    return db.execute(
        select(LandownerPayment)
        .where(LandownerPayment.project_id == project.id, LandownerPayment.is_deleted.is_(False))
        .order_by(LandownerPayment.payment_date.desc(), LandownerPayment.created_at.desc())
    ).scalars().all()


def _payment_dict(p: LandownerPayment) -> dict:
    return {
        "id": str(p.id),
        "payer_name": p.payer_name,
        "committed_total_try": _s(p.committed_total_try),
        "payment_date": p.payment_date.isoformat() if p.payment_date else None,
        "amount_try": _s(p.amount_try),
        "amount_usd": _s(p.amount_usd),
        "fx_rate_usd": _s(p.fx_rate_usd),
        "payment_type": p.payment_type,
        "description": p.description,
        "notes": p.notes,
    }


def landowner_rollup(db: Session, project: Project) -> dict:
    """SQL-side ledger rollup (§2.2): Σ amount_try/amount_usd, count, the header
    commitment (max of the repeated value) and remaining-vs-committed. Pure
    aggregation, no Python loop. NEVER feeds hakediş revenue."""
    sum_try, sum_usd, cnt, committed, missing = db.execute(
        select(
            func.coalesce(func.sum(LandownerPayment.amount_try), 0),
            func.coalesce(func.sum(LandownerPayment.amount_usd), 0),
            func.count(LandownerPayment.id),
            func.max(LandownerPayment.committed_total_try),
            func.coalesce(func.sum(_null_int(LandownerPayment.amount_usd)), 0),
        ).where(
            LandownerPayment.project_id == project.id,
            LandownerPayment.is_deleted.is_(False),
        )
    ).one()

    paid_try = money(D(sum_try))
    committed_d = money(D(committed)) if committed is not None else None
    remaining_try = money(committed_d - paid_try) if committed_d is not None else None
    pct_paid = (
        str(money(safe_div(paid_try, committed_d) * 100)) if committed_d and committed_d > 0 else None
    )
    return {
        "total_try": str(paid_try),
        "total_usd": str(money(D(sum_usd))),
        "count": int(cnt),
        "committed_total_try": str(committed_d) if committed_d is not None else None,
        "remaining_try": str(remaining_try) if remaining_try is not None else None,
        "pct_paid": pct_paid,
        "usd_missing_count": int(missing),
    }


def landowner_ledger(db: Session, project: Project) -> dict:
    """Payments list + the SQL rollup — the GET payload (§2.2)."""
    payments = [_payment_dict(p) for p in list_landowner_payments(db, project)]
    return {"payments": payments, "rollup": landowner_rollup(db, project)}


# --------------------------------------------------------------------------- #
# CR-031-C — revenue-model-aware Project P&L + m² analizi + kur-etkisi
# --------------------------------------------------------------------------- #
def sales_by_owner_side(db: Session, project: Project) -> dict:
    """SQL Σ of unit-sales revenue grouped by ``owner_side`` (the contractor /
    landowner split feed, §3.1). Pure aggregation."""
    rows = db.execute(
        select(
            UnitSale.owner_side,
            func.coalesce(func.sum(UnitSale.sale_price_try), 0),
            func.coalesce(func.sum(UnitSale.sale_price_usd), 0),
        )
        .where(UnitSale.project_id == project.id, UnitSale.is_deleted.is_(False))
        .group_by(UnitSale.owner_side)
    ).all()
    out = {"yuklenici": {"try": money(D(0)), "usd": money(D(0))},
           "arsa_sahibi": {"try": money(D(0)), "usd": money(D(0))}}
    for side, s_try, s_usd in rows:
        if side in out:
            out[side] = {"try": money(D(s_try)), "usd": money(D(s_usd))}
    return out


def cost_fx_basis(db: Session, project: Project) -> dict:
    """Coherent kur-etkisi basis: Σ original ``amount_try`` AND Σ ``amount_usd``
    snapshot over the SAME cost rows (CR-014-C scope: live, non-pending). Keeping
    both sides on one row-set makes ``cost_usd × today_rate − cost_try`` honest."""
    from app.models.cost_entry import CostEntry

    sum_try, sum_usd, missing = db.execute(
        select(
            func.coalesce(func.sum(CostEntry.amount_try), 0),
            func.coalesce(func.sum(CostEntry.amount_usd), 0),
            func.coalesce(func.sum(_null_int(CostEntry.amount_usd)), 0),
        ).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
        )
    ).one()
    return {"cost_try_original": money(D(sum_try)), "cost_usd": money(D(sum_usd)),
            "usd_missing_count": int(missing)}


def _floor_count(db: Session, project: Project) -> int:
    """Distinct non-null floors among the project's unit sales (per-floor m²)."""
    return int(db.execute(
        select(func.count(func.distinct(UnitSale.floor))).where(
            UnitSale.project_id == project.id,
            UnitSale.is_deleted.is_(False),
            UnitSale.floor.is_not(None),
        )
    ).scalar() or 0)


def project_pnl(db: Session, project: Project, today: date | None = None) -> dict:
    """The revenue-model-aware Project P&L block (§3) assembled onto the payload.

    REVENUE (§0.2, never double-counted):
      - sell-side (kat_karsiligi/yap_sat/hasilat_paylasimi) → Σ unit_sales + Σ
        landowner_payments;
      - hakedis/maliyet_kar → client_invoices (the existing rollup, reused).
    COST is read from the authoritative CR-007/014 rollup. FINANCING is a
    separable CR-015 overlay (excl/incl both exposed). m² analizi + kur-etkisi are
    derived at read-time from today's rate; nothing is written back.
    """
    from app.constants import SELL_SIDE_REVENUE_MODELS
    from app.services import financials as fin_service
    from app.services import financing as financing_service

    f = fin_service.project_financials(db, project, today=today)
    usd = fin_service.project_usd_totals(db, project)
    cost_try = money(f["forecast_final_cost_try"])
    cost_usd = money(D(usd["costs"]["amount_usd"]))

    model = project.revenue_model
    sell_side = model in SELL_SIDE_REVENUE_MODELS

    if sell_side:
        sales = sales_revenue_totals(db, project)
        land = landowner_rollup(db, project)
        revenue_try = money(sales["total_try"] + D(land["total_try"]))
        revenue_usd = money(sales["total_usd"] + D(land["total_usd"]))
        revenue_source = "sales"
        breakdown = {
            "unit_sales_try": str(sales["total_try"]),
            "unit_sales_usd": str(sales["total_usd"]),
            "landowner_try": land["total_try"],
            "landowner_usd": land["total_usd"],
            "client_invoices_try": "0.00",  # explicitly EXCLUDED (no double-count)
        }
    else:
        # hakedis / maliyet_kar — revenue is the existing hakediş rollup, reused.
        revenue_try = money(f["total_invoiced_try"])
        revenue_usd = money(D(usd["invoices"]["amount_usd"]))
        revenue_source = "hakedis"
        breakdown = {
            "client_invoices_try": str(revenue_try),
            "unit_sales_try": "0.00",
            "landowner_try": "0.00",
        }

    fin = financing_service.compute_financing_cost(db, project, today=today)
    statement = pnl_calc.pnl_statement(
        revenue_try, revenue_usd, cost_try, cost_usd,
        D(fin["total_try"]), D(fin["total_usd"]),
    )

    today_rate = fx.latest_rate(db)
    basis = cost_fx_basis(db, project)
    kur = pnl_calc.fx_effect(basis["cost_try_original"], basis["cost_usd"], today_rate)

    m2 = pnl_calc.m2_analysis(
        cost_try, cost_usd, today_rate,
        gross_m2=project.construction_gross_m2,
        net_m2=project.construction_net_m2,
        unit_count=project.unit_count,
        floor_count=_floor_count(db, project),
    )

    block = {
        "revenue_model": model,
        "revenue_source": revenue_source,
        "revenue_breakdown": breakdown,
        **statement,
        "usd_missing_count": usd["costs"]["usd_missing_count"],
        "m2_analysis": m2,
        "fx_effect": kur,
    }
    if sell_side:
        block["split"] = _contractor_split(db, project, cost_try)
    return block


def _contractor_split(db: Session, project: Project, cost_try) -> dict:
    """Contractor (yüklenici) vs landowner (arsa sahibi) split for share models —
    derived from ``contractor_share_pct`` + ``unit_sales.owner_side`` (§3.1). Cost
    is allocated by the project-level share %; null when no share is set."""
    by_side = sales_by_owner_side(db, project)
    land = landowner_rollup(db, project)
    share = project.contractor_share_pct
    if share is not None:
        contractor_cost = money(D(cost_try) * D(share) / D(100))
        landowner_cost = money(D(cost_try) - contractor_cost)
    else:
        contractor_cost = landowner_cost = None
    return {
        "contractor_share_pct": str(share) if share is not None else None,
        "contractor": {
            "sales_try": str(by_side["yuklenici"]["try"]),
            "sales_usd": str(by_side["yuklenici"]["usd"]),
            "allocated_cost_try": str(contractor_cost) if contractor_cost is not None else None,
        },
        "landowner": {
            "sales_try": str(by_side["arsa_sahibi"]["try"]),
            "sales_usd": str(by_side["arsa_sahibi"]["usd"]),
            "payments_try": land["total_try"],
            "payments_usd": land["total_usd"],
            "allocated_cost_try": str(landowner_cost) if landowner_cost is not None else None,
        },
    }
