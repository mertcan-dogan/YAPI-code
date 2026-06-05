"""Project-level financial aggregation (Section 7.1).

All inputs are plain dicts so the engine is unit-testable without the ORM.
The service layer converts ORM rows to dicts before calling in.

Expected keys
-------------
project: contract_value_try, original_budget_try, approved_variations_try,
         start_date, planned_end_date, target_margin_pct, completion_pct
cost entry: amount_try, total_with_vat_try, amount_paid_try, entry_type,
            payment_status, payment_due_date, date_paid, cost_category
client invoice: amount_try, amount_received_try, outstanding_try,
                retention_amount_try, net_due_try, due_date, payment_status,
                date_received
budget line: cost_category, original_budget_try, approved_variations_try,
             forecast_final_try
"""
from datetime import date
from decimal import Decimal

from app.calculations.money import D, money, pct, safe_div
from app.calculations.rag import compute_rag_status, rag_reason_tr, RAG_LABELS_TR
from app.constants import COST_CATEGORY_KEYS

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _is_overdue_cost(e: dict, today: date) -> bool:
    if e.get("entry_type") == "forecast":
        return False
    if e.get("payment_status") == "paid":
        return False
    due = e.get("payment_due_date")
    return due is not None and due < today


def _is_overdue_invoice(inv: dict, today: date) -> bool:
    if inv.get("payment_status") == "paid":
        return False
    if D(inv.get("outstanding_try")) <= ZERO:
        return False
    due = inv.get("due_date")
    return due is not None and due < today


def compute_project_financials(
    project: dict,
    cost_entries: list[dict],
    client_invoices: list[dict],
    budget_line_items: list[dict],
    today: date | None = None,
) -> dict:
    today = today or date.today()

    contract_value = D(project.get("contract_value_try"))

    # --- Budget (project level) ---
    revised_budget = money(
        D(project.get("original_budget_try")) + D(project.get("approved_variations_try"))
    )

    # --- Cost rollups (Section 7.1) ---
    total_committed = ZERO   # entry_type in (actual, committed), ex-VAT
    total_actual = ZERO      # entry_type == actual, ex-VAT
    total_actual_with_vat = ZERO  # for the "Gerçekleşen Maliyet" hero card (Section 4.2)
    total_paid_out = ZERO    # amount_paid_try

    for e in cost_entries:
        etype = e.get("entry_type", "actual")
        amt = D(e.get("amount_try"))
        if etype in ("actual", "committed"):
            total_committed += amt
        if etype == "actual":
            total_actual += amt
            total_actual_with_vat += D(e.get("total_with_vat_try"))
        total_paid_out += D(e.get("amount_paid_try"))

    total_committed = money(total_committed)
    total_actual = money(total_actual)
    total_actual_with_vat = money(total_actual_with_vat)
    total_paid_out = money(total_paid_out)

    remaining_budget = money(revised_budget - total_committed)

    # --- Per-category budget table (Section 4.3) ---
    categories = _compute_category_rows(cost_entries, budget_line_items, today)
    forecast_from_budget = money(sum((c["forecast_final"] for c in categories), ZERO))
    categories_over_100pct = sum(1 for c in categories if c["pct_spent"] > HUNDRED)
    categories_over_95pct = sum(1 for c in categories if c["pct_spent"] >= Decimal("95"))

    # --- Final cost forecast & margin (Section 7.1) ---
    forecast_final_cost = max(total_actual, forecast_from_budget)
    current_profit = money(contract_value - forecast_final_cost)
    margin_pct = pct(safe_div(contract_value - forecast_final_cost, contract_value) * HUNDRED)

    # --- Revenue rollups ---
    total_invoiced = money(sum((D(i.get("amount_try")) for i in client_invoices), ZERO))
    total_collected = money(sum((D(i.get("amount_received_try")) for i in client_invoices), ZERO))
    total_outstanding = money(sum((D(i.get("outstanding_try")) for i in client_invoices), ZERO))
    total_retention = money(sum((D(i.get("retention_amount_try")) for i in client_invoices), ZERO))

    net_cash_position = money(total_collected - total_paid_out)

    # --- Overdue (payables + receivables, Section 4.1) ---
    overdue_count = 0
    max_overdue_days = 0
    for e in cost_entries:
        if _is_overdue_cost(e, today):
            overdue_count += 1
            max_overdue_days = max(max_overdue_days, (today - e["payment_due_date"]).days)
    for inv in client_invoices:
        if _is_overdue_invoice(inv, today):
            overdue_count += 1
            max_overdue_days = max(max_overdue_days, (today - inv["due_date"]).days)

    # --- Time / completion ---
    start = project.get("start_date")
    planned_end = project.get("planned_end_date")
    time_completion_pct = ZERO
    estimated_finish_date = None
    if start and planned_end:
        total_days = (planned_end - start).days
        elapsed = (today - start).days
        time_completion_pct = pct(min(safe_div(elapsed, total_days) * HUNDRED, HUNDRED))
        # Tahmini Bitiş — only if forecast exceeds revised budget (Section 7.1)
        if forecast_final_cost > revised_budget and revised_budget > ZERO and total_days > 0:
            factor = safe_div(forecast_final_cost, revised_budget)
            projected_days = int(D(total_days) * factor)
            from datetime import timedelta

            estimated_finish_date = start + timedelta(days=projected_days)

    margin_pct_f = float(margin_pct)
    rag_input = {
        "margin_pct": margin_pct_f,
        "overdue_count": overdue_count,
        "max_overdue_days": max_overdue_days,
        "net_cash_position": float(net_cash_position),
        "categories_over_100pct": categories_over_100pct,
    }
    rag = compute_rag_status(rag_input)

    return {
        "contract_value_try": contract_value,
        "revised_budget_try": revised_budget,
        "total_committed_try": total_committed,
        "total_actual_try": total_actual,
        "total_actual_with_vat_try": total_actual_with_vat,
        "total_paid_out_try": total_paid_out,
        "remaining_budget_try": remaining_budget,
        "forecast_final_cost_try": forecast_final_cost,
        "current_profit_try": current_profit,
        "margin_pct": margin_pct,
        "target_margin_pct": (
            pct(project["target_margin_pct"]) if project.get("target_margin_pct") is not None else None
        ),
        "total_invoiced_try": total_invoiced,
        "total_collected_try": total_collected,
        "total_outstanding_try": total_outstanding,
        "total_retention_try": total_retention,
        "net_cash_position_try": net_cash_position,
        "overdue_count": overdue_count,
        "max_overdue_days": max_overdue_days,
        "categories_over_100pct": categories_over_100pct,
        "categories_over_95pct": categories_over_95pct,
        "time_completion_pct": time_completion_pct,
        "completion_pct": pct(project.get("completion_pct") or 0),
        "estimated_finish_date": estimated_finish_date,
        "rag_status": rag,
        "rag_label_tr": RAG_LABELS_TR[rag],
        "rag_reason_tr": rag_reason_tr(rag_input),
        "categories": categories,
    }


def _compute_category_rows(
    cost_entries: list[dict], budget_line_items: list[dict], today: date
) -> list[dict]:
    """Budget-vs-actual rows per cost category (Section 4.3)."""
    budgets = {b["cost_category"]: b for b in budget_line_items}

    # Aggregate cost entries by category.
    agg: dict[str, dict] = {}
    for e in cost_entries:
        cat = e.get("cost_category")
        if cat is None:
            continue
        a = agg.setdefault(cat, {"committed": ZERO, "invoiced": ZERO, "paid": ZERO})
        etype = e.get("entry_type", "actual")
        amt = D(e.get("amount_try"))
        if etype in ("actual", "committed"):
            a["committed"] += amt
        if etype == "actual":
            a["invoiced"] += amt
        a["paid"] += D(e.get("amount_paid_try"))

    rows: list[dict] = []
    # Iterate over every known category plus any unknown ones present in data.
    all_cats = list(COST_CATEGORY_KEYS)
    for cat in agg:
        if cat not in all_cats:
            all_cats.append(cat)

    for cat in all_cats:
        b = budgets.get(cat, {})
        a = agg.get(cat, {"committed": ZERO, "invoiced": ZERO, "paid": ZERO})
        original = D(b.get("original_budget_try"))
        variations = D(b.get("approved_variations_try"))
        revised = money(original + variations)
        committed = money(a["committed"])
        invoiced = money(a["invoiced"])
        paid = money(a["paid"])
        remaining = money(revised - committed)
        pct_spent = pct(safe_div(invoiced, revised) * HUNDRED)

        forecast_raw = b.get("forecast_final_try")
        # Forecast falls back to max(revised budget, actual invoiced) when unset.
        forecast = money(forecast_raw) if forecast_raw is not None else money(max(revised, invoiced))
        variance = money(forecast - revised)  # positive = over budget

        if variance > ZERO:
            status = "red"
        elif pct_spent > Decimal("85"):
            status = "amber"
        else:
            status = "green"

        # Skip categories that have neither budget nor activity.
        if revised == ZERO and committed == ZERO and invoiced == ZERO and paid == ZERO and forecast_raw is None:
            continue

        rows.append(
            {
                "cost_category": cat,
                "original_budget_try": original,
                "approved_variations_try": variations,
                "revised_budget_try": revised,
                "committed_try": committed,
                "invoiced_try": invoiced,
                "paid_try": paid,
                "remaining_try": remaining,
                "pct_spent": pct_spent,
                "forecast_final": forecast,
                "variance_try": variance,
                "status": status,
            }
        )
    return rows
