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


def _project_total_m2(db: Session, project: Project) -> tuple:
    """The PROJECT's total net & gross m² — the cost-allocation denominator (§1.2),
    NOT Σ of the sold units. Prefer the headline ``construction_net_m2`` /
    ``construction_gross_m2`` figures; fall back to the unit-schedule sum
    (Σ net/gross_m2_each × count) only when a headline figure is absent."""
    from app.services import units as units_service

    agg = units_service.schedule_aggregates(project.units)
    net = project.construction_net_m2
    if net is None or D(net) <= 0:
        net = agg["total_sellable_net_m2"]
    gross = project.construction_gross_m2
    if gross is None or D(gross) <= 0:
        gross = agg["total_sellable_gross_m2"]
    return net, gross


def unit_sales_pnl(db: Session, project: Project, today: date | None = None) -> dict:
    """Per-unit cost allocation + P&L over the project's unit sales (§1.2).

    Reads the authoritative construction cost, allocates it across sold units by
    each unit's share of the PROJECT's total m² (not Σ sold units), returns each
    sale enriched with cost/pnl/margin + a totals row and the basis used (net /
    gross). Empty sales → empty allocations, zeroed totals.
    """
    sales = list_unit_sales(db, project)
    costs = construction_cost_totals(db, project, today=today)
    units = [_sale_dict(s) for s in sales]
    project_net_m2, project_gross_m2 = _project_total_m2(db, project)
    result = pnl_calc.allocate_unit_costs(
        units, costs["total_try"], costs["total_usd"], project_net_m2, project_gross_m2,
    )
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
    landowner split feed, §3.1) — TRY/USD + count per side. Pure aggregation.

    CR-053: the operator P&L revenue lane reads the ``yuklenici`` side from here
    (the contractor's OWN sales); ``arsa_sahibi`` sales are surfaced but EXCLUDED
    from revenue and from cash-in (the landowner's flats are not the contractor's
    money — their build cost is already in the construction total, §0)."""
    rows = db.execute(
        select(
            UnitSale.owner_side,
            func.coalesce(func.sum(UnitSale.sale_price_try), 0),
            func.coalesce(func.sum(UnitSale.sale_price_usd), 0),
            func.count(UnitSale.id),
        )
        .where(UnitSale.project_id == project.id, UnitSale.is_deleted.is_(False))
        .group_by(UnitSale.owner_side)
    ).all()
    out = {"yuklenici": {"try": money(D(0)), "usd": money(D(0)), "count": 0},
           "arsa_sahibi": {"try": money(D(0)), "usd": money(D(0)), "count": 0}}
    for side, s_try, s_usd, cnt in rows:
        if side in out:
            out[side] = {"try": money(D(s_try)), "usd": money(D(s_usd)), "count": int(cnt)}
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


def revenue_cost_totals(db: Session, project: Project, today: date | None = None) -> dict:
    """The single revenue-model-aware revenue/cost selection (§0.2) — the ONE
    place the no-double-count rule lives, shared by the P&L (§3) and IRR/ROI (§4).

    CR-053 — the founder's OPERATOR model for sell-side projects:
    * REVENUE = the contractor's OWN flat sales (``unit_sales`` with
      ``owner_side = yuklenici``) **+** any CASH contribution from the landowner
      (``landowner_payments``, now defined as cash). The ``arsa_sahibi`` sales are
      EXCLUDED — those flats are the landowner's, not the contractor's money.
    * The contributed LAND is neither revenue nor a separate cost — its cost is
      already embodied in the construction of the given-away flats (the authoritative
      rollup includes every flat built). It is surfaced as ``efektif arsa maliyeti``
      (derived, read-time; see ``project_pnl``), never added here.
    * COST stays the authoritative CR-007/014 rollup (which now also counts any
      ``kira_yardimi`` cost entries as normal cost — no special path).

    hakedis/maliyet_kar → client_invoices (existing rollup). The two revenue sources
    are NEVER summed; correctness is DATA-DRIVEN (sale ``owner_side`` + cash entries),
    not ``deal_structure``-driven, so a mis-set deal_structure cannot corrupt it.
    """
    from app.constants import SELL_SIDE_REVENUE_MODELS
    from app.services import financials as fin_service

    f = fin_service.project_financials(db, project, today=today)
    usd = fin_service.project_usd_totals(db, project)
    cost_try = money(f["forecast_final_cost_try"])
    cost_usd = money(D(usd["costs"]["amount_usd"]))

    if project.revenue_model in SELL_SIDE_REVENUE_MODELS:
        by_side = sales_by_owner_side(db, project)
        land = landowner_rollup(db, project)
        yk_try, yk_usd = by_side["yuklenici"]["try"], by_side["yuklenici"]["usd"]
        as_try, as_usd = by_side["arsa_sahibi"]["try"], by_side["arsa_sahibi"]["usd"]
        # Operator revenue = contractor's own sales + cash contributions ONLY.
        revenue_try = money(yk_try + D(land["total_try"]))
        revenue_usd = money(yk_usd + D(land["total_usd"]))
        revenue_source = "sales"
        breakdown = {
            # "unit_sales" = the contractor's OWN (yuklenici) sales — the revenue lane.
            "unit_sales_try": str(yk_try),
            "unit_sales_usd": str(yk_usd),
            # arsa_sahibi sales: informational only, EXCLUDED from revenue (non-cash land).
            "arsa_sahibi_sales_try": str(as_try),
            "arsa_sahibi_sales_usd": str(as_usd),
            "landowner_try": land["total_try"],   # cash contributions → revenue
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
    return {
        "revenue_try": revenue_try, "revenue_usd": revenue_usd,
        "cost_try": cost_try, "cost_usd": cost_usd,
        "revenue_source": revenue_source, "revenue_breakdown": breakdown,
        "usd_missing_count": usd["costs"]["usd_missing_count"],
    }


def project_pnl(db: Session, project: Project, today: date | None = None) -> dict:
    """The revenue-model-aware Project P&L block (§3) assembled onto the payload.

    REVENUE (§0.2, never double-counted): see ``revenue_cost_totals``. COST is the
    authoritative CR-007/014 rollup. FINANCING is a separable CR-015 overlay
    (excl/incl both exposed). m² analizi + kur-etkisi are derived at read-time from
    today's rate; nothing is written back.
    """
    from app.services import financing as financing_service

    rc = revenue_cost_totals(db, project, today=today)
    revenue_try, revenue_usd = rc["revenue_try"], rc["revenue_usd"]
    cost_try, cost_usd = rc["cost_try"], rc["cost_usd"]
    revenue_source, breakdown = rc["revenue_source"], rc["revenue_breakdown"]
    sell_side = revenue_source == "sales"
    model = project.revenue_model

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
        "usd_missing_count": rc["usd_missing_count"],
        "m2_analysis": m2,
        "fx_effect": kur,
    }
    if sell_side:
        block["split"] = _contractor_split(db, project, cost_try)
        # CR-053 — efektif arsa maliyeti (derived, informational): construction ×
        # landowner share. NEVER added into revenue or re-added to cost (the land's
        # cost is already in the construction total via the given-away flats, §0/§4).
        share, basis = _landowner_share(db, project)
        if share is not None:
            block["efektif_arsa_maliyeti_try"] = str(money(D(cost_try) * share))
            block["efektif_arsa_maliyeti_usd"] = str(money(D(cost_usd) * share))
            block["landowner_share_pct"] = str(money(share * D(100)))
        else:
            block["efektif_arsa_maliyeti_try"] = None
            block["efektif_arsa_maliyeti_usd"] = None
            block["landowner_share_pct"] = None
        block["landowner_share_basis"] = basis  # "units" | "pct" | None
        # CR-053 §2 — the planned "what's mine to sell" split.
        block["planned_split"] = _planned_split(db, project)
    return block


def _landowner_share(db: Session, project: Project) -> tuple:
    """CR-053 — the robust landowner share (Decimal fraction 0..1) + its basis.

    Prefer the EXPLICIT per-unit split (Σ arsa_sahibi gross m² ÷ Σ all gross m²)
    when a unit schedule exists; else fall back to ``(1 − contractor_share_pct)``;
    else ``(None, None)`` so efektif arsa maliyeti degrades to "–". Mirrors CR-031's
    "prefer explicit, fall back" denominator discipline; degrade, never raise."""
    from app.services import units as units_service

    agg = units_service.split_aggregates(project.units)
    if agg["landowner_share"] is not None:
        return agg["landowner_share"], "units"
    if project.contractor_share_pct is not None:
        return (D(100) - D(project.contractor_share_pct)) / D(100), "pct"
    return None, None


def _planned_split(db: Session, project: Project) -> dict:
    """CR-053 §2 — the planned unit split: the contractor's sellable stock vs the
    landowner's share (units/m² from the schedule), what's SOLD (the contractor's
    own ``yuklenici`` unit_sales) and the REMAINING inventory + its projected value.

    Remaining value prorates the schedule's contractor estimated-sales by the unsold
    fraction (null when the schedule carries no prices). Degrades to zeros / null
    when no schedule exists."""
    from app.services import units as units_service

    agg = units_service.split_aggregates(project.units)
    by_side = sales_by_owner_side(db, project)
    contractor = agg["contractor"]
    sellable_units = contractor["units"]
    sold_units = by_side["yuklenici"]["count"]
    remaining_units = max(0, sellable_units - sold_units)

    est = contractor["estimated_sales_try"]
    remaining_value = None
    if est is not None and sellable_units > 0:
        remaining_value = str(money(D(est) * D(remaining_units) / D(sellable_units)))

    return {
        "has_schedule": agg["has_schedule"],
        "total_gross_m2": agg["total_gross_m2"],
        "contractor": contractor,
        "landowner": agg["landowner"],
        "sold": {
            "units": sold_units,
            "value_try": str(by_side["yuklenici"]["try"]),
            "value_usd": str(by_side["yuklenici"]["usd"]),
        },
        "remaining": {"units": remaining_units, "projected_value_try": remaining_value},
    }


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


# --------------------------------------------------------------------------- #
# CR-031-D — dated net-cash-flow series → IRR / ROI
# --------------------------------------------------------------------------- #
def cashflow_series(db: Session, project: Project) -> tuple[list, list]:
    """Dated, signed net-cash-flow series in TRY and USD (§4.1). Outflows = cost
    entries (by entry_date, NEGATIVE); inflows = the revenue-model-aware lane
    (POSITIVE): sell-side → the contractor's OWN (yüklenici) unit_sales (sale_date)
    + landowner cash contributions (payment_date); hakedis/maliyet_kar →
    client_invoices (invoice_date, matching the accrual P&L).

    CR-053: the IRR/ROI series reads the SAME operator lane as ``revenue_cost_totals``
    and ``financials.cashflow_inflows`` — ``arsa_sahibi`` sales are the landowner's
    money (their flats) and are EXCLUDED, so the investment-return block never
    contradicts the operator revenue (§3 "one selector").

    USD rows are included only where a CR-014 snapshot exists (null USD is skipped
    so a missing rate never poisons the USD IRR). Returns (try_flows, usd_flows).
    """
    from app.constants import OWNER_SIDE_YUKLENICI, SELL_SIDE_REVENUE_MODELS
    from app.models.client_invoice import ClientInvoice
    from app.models.cost_entry import CostEntry

    try_flows: list[tuple] = []
    usd_flows: list[tuple] = []

    def add(d, amt_try, amt_usd, sign):
        if d is None:
            return
        if amt_try is not None:
            try_flows.append((d, sign * D(amt_try)))
        if amt_usd is not None:
            usd_flows.append((d, sign * D(amt_usd)))

    # Outflows — authoritative cost rows (live, non-pending). Uses ex-VAT
    # ``amount_try`` so the dated series sums to the SAME basis as the P&L Maliyet
    # (forecast_final_cost, built from ex-VAT ``amount_try``). Using the
    # VAT-inclusive ``total_with_vat_try`` here overstated IRR outflows by the VAT
    # rate vs. the P&L cost line (input VAT is recoverable / pass-through).
    costs = db.execute(
        select(CostEntry.entry_date, CostEntry.amount_try, CostEntry.amount_usd).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
        )
    ).all()
    for entry_date, amt_try, amt_usd in costs:
        add(entry_date, amt_try, amt_usd, D(-1))

    # Inflows — revenue-model-aware (CR-053 operator lane: yüklenici sales + cash).
    if project.revenue_model in SELL_SIDE_REVENUE_MODELS:
        for s in list_unit_sales(db, project):
            # arsa_sahibi sales are the landowner's money, not the contractor's cash.
            if s.owner_side != OWNER_SIDE_YUKLENICI:
                continue
            add(s.sale_date, s.sale_price_try, s.sale_price_usd, D(1))
        for p in list_landowner_payments(db, project):
            add(p.payment_date, p.amount_try, p.amount_usd, D(1))
    else:
        invs = db.execute(
            select(ClientInvoice.invoice_date, ClientInvoice.amount_try, ClientInvoice.amount_usd).where(
                ClientInvoice.project_id == project.id,
                ClientInvoice.is_deleted.is_(False),
            )
        ).all()
        for inv_date, amt_try, amt_usd in invs:
            add(inv_date, amt_try, amt_usd, D(1))

    return try_flows, usd_flows


def investment_return(db: Session, project: Project, today: date | None = None) -> dict:
    """IRR/ROI investment-return block (§4): XIRR (TRY & USD) over the dated
    series + ROI + duration + per-m²/unit getiri + yearly summary rows. Degenerate
    (single-sign) series → null IRR, never an exception."""
    rc = revenue_cost_totals(db, project, today=today)
    try_flows, usd_flows = cashflow_series(db, project)

    all_dates = [d for d, _ in try_flows]
    last_date = max(all_dates) if all_dates else None

    block = pnl_calc.investment_return(
        try_flows, usd_flows,
        revenue_try=rc["revenue_try"], cost_try=rc["cost_try"],
        start_date=project.start_date, last_date=last_date,
        net_m2=project.construction_net_m2, unit_count=project.unit_count,
    )
    block["revenue_source"] = rc["revenue_source"]
    block["yearly"] = pnl_calc.yearly_cashflow_rows(try_flows, usd_flows)
    return block
