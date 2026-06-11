"""Load project-related rows and run the calculation engine (Section 7)."""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations import compute_monthly_cashflow, compute_project_financials
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


def load_project_inputs(db: Session, project: Project) -> tuple[list[dict], list[dict], list[dict]]:
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

    cost_dicts = [_cost_dict(c) for c in costs]
    invoice_dicts = [_invoice_dict(i) for i in invoices]
    budget_dicts = [
        {
            "cost_category": b.cost_category,
            "original_budget_try": b.original_budget_try,
            "approved_variations_try": b.approved_variations_try,
            "forecast_final_try": b.forecast_final_try,
        }
        for b in budgets
    ]
    return cost_dicts, invoice_dicts, budget_dicts


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
    cost_to_date = D(0)
    actual_by_cat: dict[str, object] = {}
    for c in costs:
        if c.get("entry_type") == "actual":
            twv = D(c.get("total_with_vat_try"))
            cost_to_date += twv
            cat = c.get("cost_category")
            actual_by_cat[cat] = D(actual_by_cat.get(cat, D(0))) + twv
    cost_to_date = money(cost_to_date)

    # Estimated final cost: per-category forecast_final_try if set, else actuals.
    budget_by_cat = {b["cost_category"]: b for b in budgets}
    all_cats = set(budget_by_cat) | set(actual_by_cat)
    forecast_final_cost = D(0)
    for cat in all_cats:
        b = budget_by_cat.get(cat)
        if b and b.get("forecast_final_try") is not None:
            forecast_final_cost += D(b["forecast_final_try"])
        else:
            forecast_final_cost += D(actual_by_cat.get(cat, D(0)))
    forecast_final_cost = money(forecast_final_cost)

    cost_to_complete = money(forecast_final_cost - cost_to_date)
    margin_pct = pct(safe_div(contract - forecast_final_cost, contract) * 100)

    return {
        "original_budget_try": str(original_budget),
        "revised_budget_try": str(revised_budget),
        "cost_to_date_try": str(cost_to_date),
        "cost_to_complete_try": str(cost_to_complete),
        "forecast_final_cost_try": str(forecast_final_cost),
        "forecast_final_margin_pct": str(margin_pct),
        "over_budget": forecast_final_cost > revised_budget,
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
