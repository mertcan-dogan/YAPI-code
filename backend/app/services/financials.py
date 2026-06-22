"""Load project-related rows and run the calculation engine (Section 7)."""
import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.calculations import compute_monthly_cashflow, compute_project_financials, opening_balance
from app.calculations.money import D, money
from app.models.budget_line_item import BudgetLineItem
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.project import Project


def _project_dict(p: Project) -> dict:
    return {
        "contract_value_try": p.contract_value_try,
        "original_budget_try": p.original_budget_try,
        "approved_variations_try": p.approved_variations_try,
        "start_date": p.start_date,
        "planned_end_date": p.planned_end_date,
        "target_margin_pct": p.target_margin_pct,
        "completion_pct": p.completion_pct,
    }


def _cost_dict(c: CostEntry) -> dict:
    return {
        # CR-023: id + commitment_id let the rollup net linked actuals out of
        # their commitment (open_commitment) so exposure never double-counts.
        "id": c.id,
        "commitment_id": c.commitment_id,
        "amount_try": c.amount_try,
        "amount_eur": c.amount_eur,
        "total_with_vat_try": c.total_with_vat_try,
        "amount_paid_try": c.amount_paid_try,
        "entry_type": c.entry_type,
        "payment_status": c.payment_status,
        "payment_due_date": c.payment_due_date,
        "date_paid": c.date_paid,
        "entry_date": c.entry_date,
        "cost_category": c.cost_category,
    }


def _invoice_dict(i: ClientInvoice) -> dict:
    return {
        "amount_try": i.amount_try,
        "amount_received_try": i.amount_received_try,
        "outstanding_try": i.outstanding_try,
        "retention_amount_try": i.retention_amount_try,
        "net_due_try": i.net_due_try,
        "due_date": i.due_date,
        "date_received": i.date_received,
        "payment_status": i.payment_status,
    }


# --------------------------------------------------------------------------- #
# Per-request input cache (perf). The same project's cost/invoice/budget rows are
# loaded several times within one request — project_financials, project_cashflow,
# forecast_at_completion and margin_bridge each call load_project_inputs, so the
# single-project dashboard reloaded them 4× (12 queries). The company dashboard /
# project list reloaded them once PER PROJECT (N+1). We memoise the loaded inputs
# on the Session (db.info) keyed by project id: read endpoints reuse them for free
# and ``prime_project_inputs`` batch-loads many projects in 3 queries. The cache
# is correctness-safe — any flush of a CostEntry/ClientInvoice/BudgetLineItem
# clears it (see the after_flush listener below), so a read-after-write in the
# same session always recomputes from fresh rows.
# --------------------------------------------------------------------------- #
_CACHE_KEY = "_project_inputs_cache"
_CACHED_MODELS = (CostEntry, ClientInvoice, BudgetLineItem)


def _inputs_cache(db: Session) -> dict:
    return db.info.setdefault(_CACHE_KEY, {})


def _budget_dict(b: BudgetLineItem) -> dict:
    return {
        "cost_category": b.cost_category,
        "original_budget_try": b.original_budget_try,
        "approved_variations_try": b.approved_variations_try,
        "forecast_final_try": b.forecast_final_try,
    }


def load_project_inputs(db: Session, project: Project) -> tuple[list[dict], list[dict], list[dict]]:
    cache = _inputs_cache(db)
    cached = cache.get(project.id)
    if cached is not None:
        return cached

    costs = db.execute(
        select(CostEntry).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),  # CR-003-J: exclude unapproved
        )
    ).scalars().all()
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id == project.id, ClientInvoice.is_deleted.is_(False)
        )
    ).scalars().all()
    budgets = db.execute(
        select(BudgetLineItem).where(
            BudgetLineItem.project_id == project.id, BudgetLineItem.is_deleted.is_(False)
        )
    ).scalars().all()

    result = (
        [_cost_dict(c) for c in costs],
        [_invoice_dict(i) for i in invoices],
        [_budget_dict(b) for b in budgets],
    )
    cache[project.id] = result
    return result


def prime_project_inputs(db: Session, projects) -> None:
    """Batch-load inputs for many projects in 3 queries (not 3×N) and populate the
    per-session cache, so the following ``load_project_inputs``/``project_financials``
    calls are query-free. Used by the project list + company dashboard to kill the
    N+1. No-op for projects already cached."""
    cache = _inputs_cache(db)
    ids = [p.id for p in projects if p.id not in cache]
    if not ids:
        return

    costs_by: dict = defaultdict(list)
    for c in db.execute(
        select(CostEntry).where(
            CostEntry.project_id.in_(ids),
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
        )
    ).scalars().all():
        costs_by[c.project_id].append(_cost_dict(c))

    inv_by: dict = defaultdict(list)
    for i in db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id.in_(ids), ClientInvoice.is_deleted.is_(False)
        )
    ).scalars().all():
        inv_by[i.project_id].append(_invoice_dict(i))

    bud_by: dict = defaultdict(list)
    for b in db.execute(
        select(BudgetLineItem).where(
            BudgetLineItem.project_id.in_(ids), BudgetLineItem.is_deleted.is_(False)
        )
    ).scalars().all():
        bud_by[b.project_id].append(_budget_dict(b))

    for pid in ids:
        cache[pid] = (costs_by.get(pid, []), inv_by.get(pid, []), bud_by.get(pid, []))


@event.listens_for(Session, "after_flush")
def _invalidate_project_inputs_cache(session: Session, flush_context) -> None:
    """Clear the per-session input cache whenever a cost/invoice/budget row is
    flushed, so any read-after-write in the same session recomputes from fresh
    rows (the cache is purely a within-request read optimization)."""
    cache = session.info.get(_CACHE_KEY)
    if not cache:
        return
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, _CACHED_MODELS):
            cache.clear()
            return


def project_financials(
    db: Session, project: Project, today: date | None = None, extra_category_keys: list[str] | None = None
) -> dict:
    costs, invoices, budgets = load_project_inputs(db, project)
    return compute_project_financials(
        _project_dict(project), costs, invoices, budgets, today=today, extra_category_keys=extra_category_keys
    )


def project_cashflow(db: Session, project: Project, today: date | None = None) -> list[dict]:
    costs, invoices, _ = load_project_inputs(db, project)
    return compute_monthly_cashflow(costs, invoices, today=today)


def project_cashflow_window(
    db: Session, project: Project, from_month: str | None = None,
    to_month: str | None = None, today: date | None = None,
) -> dict:
    """Cashflow rows for a custom month range (YYYY-MM..YYYY-MM) plus the opening
    balance carried in from before the range. Omitting from/to falls back to the
    fixed rolling window with a zero opening balance (today's behavior)."""
    costs, invoices, _ = load_project_inputs(db, project)
    rows = compute_monthly_cashflow(costs, invoices, today=today, from_month=from_month, to_month=to_month)
    opening = opening_balance(costs, invoices, from_month, today=today) if (from_month and to_month) else money(D(0))
    return {"rows": rows, "opening_balance_try": opening}


# --------------------------------------------------------------------------- #
# CR-014-C — USD aggregates (point-in-time snapshot sums)
# --------------------------------------------------------------------------- #
def usd_aggregates(
    db: Session, *, project_ids: list | None = None, company_id=None
) -> dict:
    """USD totals = the SUM of per-row ``amount_usd`` SNAPSHOTS (point-in-time,
    §0.2) — NOT ``total_try ÷ today's rate``. Each row was valued at the rate of
    its own relevant date (CR-014-B); we just add those stored snapshots up.

    Summed exactly with Decimal (dialect-agnostic). Rows with a null snapshot
    (pre-history / fetch failure) are silently ignored by a sum, which would
    UNDERSTATE the total — so each total is paired with ``usd_missing_count`` so
    the UI can warn "N kayıt için kur bulunamadı". TRY figures are untouched.

    Cost scope mirrors the dashboard (exclude soft-deleted + pending-approval);
    invoices exclude soft-deleted.
    """
    def _agg(model, extra_filters: list) -> dict:
        filters = [model.is_deleted.is_(False), *extra_filters]
        if project_ids is not None:
            filters.append(model.project_id.in_(project_ids))
        if company_id is not None:
            filters.append(model.company_id == company_id)
        vals = db.execute(select(model.amount_usd).where(*filters)).scalars().all()
        total = sum((D(v) for v in vals if v is not None), D(0))
        missing = sum(1 for v in vals if v is None)
        return {"amount_usd": str(money(total)), "usd_missing_count": missing}

    return {
        "costs": _agg(CostEntry, [CostEntry.pending_approval.is_(False)]),
        "invoices": _agg(ClientInvoice, []),
    }


def project_usd_totals(db: Session, project: Project) -> dict:
    """Per-row USD snapshot sums for a single project (§3.1)."""
    return usd_aggregates(db, project_ids=[project.id])


def period_summary(db: Session, project: Project, from_date: date, to_date: date) -> dict:
    """Activity totals for a project within [from_date, to_date] (inclusive).

    Cost INCURRED by entry_date (VAT-incl, matching the cashflow's actual-out rule
    and the dashboard exclusions), invoiced by invoice_date (net amount_try, like
    the headline "İşverene Faturalanan"), collected by date_received. USD figures
    are the SUM of the CR-014 ``amount_usd`` snapshots on the same rows, with a
    count of contributing rows that lack a snapshot. Exact Decimal; dialect-safe
    (Python date bounds work on SQLite + Postgres). Company-scoped.
    """
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.project_id == project.id,
            CostEntry.company_id == project.company_id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),  # match dashboard exclusion
            CostEntry.entry_date >= from_date,
            CostEntry.entry_date <= to_date,
        )
    ).scalars().all()
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id == project.id,
            ClientInvoice.company_id == project.company_id,
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalars().all()

    issued = [i for i in invoices if i.invoice_date and from_date <= i.invoice_date <= to_date]
    collected = [i for i in invoices if i.date_received and from_date <= i.date_received <= to_date]

    cost_incurred = money(sum((D(c.total_with_vat_try) for c in costs), D(0)))
    invoiced = money(sum((D(i.amount_try) for i in issued), D(0)))
    collected_try = money(sum((D(i.amount_received_try) for i in collected), D(0)))

    def _usd_sum(rows):
        return money(sum((D(r.amount_usd) for r in rows if r.amount_usd is not None), D(0)))

    # One missing-snapshot count over the distinct contributing rows.
    missing_invoice_ids = {i.id for i in issued if i.amount_usd is None} | {
        i.id for i in collected if i.amount_usd is None
    }
    usd_missing = sum(1 for c in costs if c.amount_usd is None) + len(missing_invoice_ids)

    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "cost_incurred_try": str(cost_incurred),
        "invoiced_try": str(invoiced),
        "collected_try": str(collected_try),
        "net_try": str(money(collected_try - cost_incurred)),
        "cost_incurred_usd": str(_usd_sum(costs)),
        "invoiced_usd": str(_usd_sum(issued)),
        "collected_usd": str(_usd_sum(collected)),
        "usd_missing_count": usd_missing,
        "cost_count": len(costs),
        "invoice_count": len(issued),
        "collected_count": len(collected),
    }


def cash_need_windows(db: Session, project: Project, today: date | None = None) -> list[dict]:
    """CR-004-M: net cash need over the next 30/60/90 days.

    need = planned outflows (unpaid costs due in window) - expected inflows
    (outstanding invoices due in window). Positive => cash shortfall (red),
    negative => surplus (green).
    """
    from datetime import timedelta

    from app.calculations.money import D, money

    today = today or date.today()
    costs = db.execute(
        select(CostEntry).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.payment_status != "paid",
            CostEntry.payment_due_date.is_not(None),
        )
    ).scalars().all()
    invoices = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id == project.id,
            ClientInvoice.is_deleted.is_(False),
            ClientInvoice.payment_status != "paid",
        )
    ).scalars().all()

    windows = []
    for days in (30, 60, 90):
        horizon = today + timedelta(days=days)
        out = sum(
            (D(c.total_with_vat_try) - D(c.amount_paid_try) for c in costs
             if c.payment_due_date and today <= c.payment_due_date <= horizon),
            D(0),
        )
        inflow = sum(
            (D(i.outstanding_try) for i in invoices
             if i.due_date and today <= i.due_date <= horizon and D(i.outstanding_try) > 0),
            D(0),
        )
        need = out - inflow
        windows.append({
            "days": days,
            "planned_out_try": str(money(out)),
            "expected_in_try": str(money(inflow)),
            "net_need_try": str(money(need)),
            "shortfall": need > 0,  # True => need cash (red)
        })
    return windows


def cashflow_month_detail(db: Session, project: Project, month_str: str) -> dict:
    """CR-005-D: per-month drill-down for the cash-flow drawer.

    Returns the unpaid cost entries due in the month ("Gider Tahminleri") and the
    uncollected client invoices due in the month ("Beklenen Tahsilat"), filtered
    server-side with a proper [first_day, last_day] date range (no timezone/string
    slicing issues), plus the period totals.
    """
    import calendar
    from datetime import date as _date

    from app.calculations.money import D, money

    year, month = int(month_str.split("-")[0]), int(month_str.split("-")[1])
    first_day = _date(year, month, 1)
    last_day = _date(year, month, calendar.monthrange(year, month)[1])

    cost_rows = db.execute(
        select(CostEntry).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
            CostEntry.pending_approval.is_(False),
            CostEntry.payment_status != "paid",
            CostEntry.payment_due_date >= first_day,
            CostEntry.payment_due_date <= last_day,
        )
    ).scalars().all()

    invoice_rows = db.execute(
        select(ClientInvoice).where(
            ClientInvoice.project_id == project.id,
            ClientInvoice.is_deleted.is_(False),
            ClientInvoice.payment_status != "paid",
            ClientInvoice.due_date >= first_day,
            ClientInvoice.due_date <= last_day,
        )
    ).scalars().all()

    costs = []
    out_total = D(0)
    for c in cost_rows:
        remaining = D(c.total_with_vat_try) - D(c.amount_paid_try)
        out_total += remaining
        costs.append({
            "id": str(c.id),
            "cost_category": c.cost_category,
            "supplier_name": c.supplier_name,
            "description": c.description,
            "total_with_vat_try": str(money(D(c.total_with_vat_try))),
            "amount_paid_try": str(money(D(c.amount_paid_try))),
            "remaining_try": str(money(remaining)),
            "payment_due_date": c.payment_due_date.isoformat() if c.payment_due_date else None,
            "payment_status": c.payment_status,
        })

    invoices = []
    in_total = D(0)
    for i in invoice_rows:
        outstanding = D(i.outstanding_try)
        in_total += outstanding
        invoices.append({
            "id": str(i.id),
            "invoice_number": i.invoice_number,
            "hakkedis_period": i.hakkedis_period,
            "outstanding_try": str(money(outstanding)),
            "net_due_try": str(money(D(i.net_due_try))),
            "due_date": i.due_date.isoformat() if i.due_date else None,
            "payment_status": i.payment_status,
        })

    return {
        "month": month_str,
        "costs": costs,
        "invoices": invoices,
        "total_out_try": str(money(out_total)),
        "total_in_try": str(money(in_total)),
        "net_try": str(money(in_total - out_total)),
    }


def forecast_at_completion(db: Session, project: Project) -> dict:
    """CR-003-F: Forecast-at-Completion KPIs (uses VAT-inclusive cost totals)."""
    from app.calculations.money import D, money, pct, safe_div

    costs, _invoices, budgets = load_project_inputs(db, project)
    contract = D(project.contract_value_try)

    original_budget = money(sum((D(b["original_budget_try"]) for b in budgets), D(0)))
    revised_budget = money(
        sum((D(b["original_budget_try"]) + D(b["approved_variations_try"]) for b in budgets), D(0))
    )

    # Actual (entry_type=actual) cost-to-date and per-category VAT-inclusive totals.
    # CR-023: also roll up open commitments per category (VAT-inclusive, relieved
    # by any linked actuals) so the forecast sees money committed-but-not-yet-billed.
    from app.calculations.project_financials import open_commitment, relief_by_commitment

    relief = relief_by_commitment(costs, "total_with_vat_try")
    cost_to_date = D(0)
    actual_by_cat: dict[str, object] = {}
    open_committed_by_cat: dict[str, object] = {}
    for c in costs:
        etype = c.get("entry_type")
        cat = c.get("cost_category")
        if etype == "actual":
            twv = D(c.get("total_with_vat_try"))
            cost_to_date += twv
            actual_by_cat[cat] = D(actual_by_cat.get(cat, D(0))) + twv
        elif etype == "committed":
            oc = open_commitment(c, relief, "total_with_vat_try")
            open_committed_by_cat[cat] = D(open_committed_by_cat.get(cat, D(0))) + oc
    cost_to_date = money(cost_to_date)

    # Estimated final cost per category: max(budget-derived forecast, actual + open
    # committed). Open commitments are money you WILL spend (CR-023 §5.3), so the
    # forecast can never fall below them even when a budget forecast is set lower.
    budget_by_cat = {b["cost_category"]: b for b in budgets}
    all_cats = set(budget_by_cat) | set(actual_by_cat) | set(open_committed_by_cat)
    forecast_final_cost = D(0)
    for cat in all_cats:
        b = budget_by_cat.get(cat)
        actual_cat = D(actual_by_cat.get(cat, D(0)))
        exposure_cat = actual_cat + D(open_committed_by_cat.get(cat, D(0)))
        if b and b.get("forecast_final_try") is not None:
            base = D(b["forecast_final_try"])
        else:
            base = actual_cat
        forecast_final_cost += max(base, exposure_cat)
    forecast_final_cost = money(forecast_final_cost)

    cost_to_complete = money(forecast_final_cost - cost_to_date)
    margin_pct = pct(safe_div(contract - forecast_final_cost, contract) * 100)

    # CR-015-B: modeled financing cost is a SEPARABLE forecast overlay (§0.2).
    # It is added ONLY to the *_with_financing figures below — the base forecast
    # (and all actual totals/margin elsewhere) stay byte-identical whether
    # financing is on or off. When off, the total is 0.00 and the variants equal
    # the base, so existing consumers are unaffected.
    from app.services import financing as financing_service

    fin = financing_service.compute_financing_cost(db, project)
    fin_try = D(fin["total_try"])
    forecast_with_financing = money(forecast_final_cost + fin_try)
    margin_with_financing = pct(safe_div(contract - forecast_with_financing, contract) * 100)

    return {
        "original_budget_try": str(original_budget),
        "revised_budget_try": str(revised_budget),
        "cost_to_date_try": str(cost_to_date),
        "cost_to_complete_try": str(cost_to_complete),
        "forecast_final_cost_try": str(forecast_final_cost),
        "forecast_final_margin_pct": str(margin_pct),
        "over_budget": forecast_final_cost > revised_budget,
        # Separable financing overlay (0.00 / identical to base when disabled).
        "financing_cost_try": fin["total_try"],
        "forecast_final_cost_with_financing_try": str(forecast_with_financing),
        "forecast_final_margin_with_financing_pct": str(margin_with_financing),
    }


def margin_bridge(db: Session, project: Project) -> dict:
    """CR-003-G: margin waterfall components (TRY)."""
    from app.calculations.money import D, money, safe_div

    costs, _invoices, budgets = load_project_inputs(db, project)
    contract = D(project.contract_value_try)

    # Original expected margin: target margin % if set, else (contract - original budget)/contract.
    original_budget = sum((D(b["original_budget_try"]) for b in budgets), D(0))
    if project.target_margin_pct is not None:
        original_margin = money(contract * D(project.target_margin_pct) / D(100))
    else:
        original_margin = money(contract - original_budget)

    approved_variations = money(sum((D(b["approved_variations_try"]) for b in budgets), D(0)))

    # Pending variations from the variations module (CR-003-I), if present.
    pending_variations = D(0)
    try:
        from app.models.variation import Variation

        for v in db.execute(
            select(Variation).where(
                Variation.project_id == project.id, Variation.status == "pending",
                Variation.is_deleted.is_(False),
            )
        ).scalars().all():
            pending_variations += D(v.value_try)
    except Exception:
        pending_variations = D(0)
    pending_variations = money(pending_variations)

    # Per-category overruns / savings (forecast vs original budget).
    actual_by_cat: dict = {}
    for c in costs:
        if c.get("entry_type") == "actual":
            cat = c.get("cost_category")
            actual_by_cat[cat] = D(actual_by_cat.get(cat, D(0))) + D(c.get("total_with_vat_try"))
    overruns = D(0)
    savings = D(0)
    for b in budgets:
        cat = b["cost_category"]
        original = D(b["original_budget_try"])
        forecast = D(b["forecast_final_try"]) if b["forecast_final_try"] is not None else D(actual_by_cat.get(cat, D(0)))
        diff = forecast - original
        if original > 0:  # only categories with a budget contribute over/under
            if diff > 0:
                overruns += diff
            elif diff < 0:
                savings += -diff

    fac = forecast_at_completion(db, project)
    current_margin = money(contract - D(fac["forecast_final_cost_try"]))

    return {
        "original_margin_try": str(original_margin),
        "approved_variations_try": str(approved_variations),
        "pending_variations_try": str(pending_variations),
        "cost_overruns_try": str(money(-overruns)),   # negative impact
        "cost_savings_try": str(money(savings)),       # positive impact
        "current_margin_try": str(current_margin),
    }
