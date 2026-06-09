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
            CostEntry.project_id == project.id, CostEntry.is_deleted.is_(False)
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
