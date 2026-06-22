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
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.calculations.money import D, money, pct, safe_div
from app.calculations.rag import compute_rag_status, rag_reason_tr, RAG_LABELS_TR
from app.constants import COST_CATEGORY_KEYS

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def relief_by_commitment(cost_entries: list[dict], amount_key: str = "amount_try") -> dict:
    """CR-023: Σ of linked-actual amounts per commitment_id.

    An *actual* entry with ``commitment_id`` set "relieves" that committed entry.
    ``amount_key`` picks the measure — ex-VAT (``amount_try``) for the budget
    rollup, VAT-inclusive (``total_with_vat_try``) for the forecast.
    """
    relief: dict = defaultdict(lambda: ZERO)
    for e in cost_entries:
        if e.get("entry_type", "actual") == "actual" and e.get("commitment_id"):
            relief[e["commitment_id"]] += D(e.get(amount_key))
    return relief


def open_commitment(c: dict, relief: dict, amount_key: str = "amount_try") -> Decimal:
    """Open (unrelieved) portion of a committed entry: max(amount − Σ linked, 0)."""
    return max(D(c.get(amount_key)) - D(relief.get(c.get("id"), ZERO)), ZERO)


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
    extra_category_keys: list[str] | None = None,
) -> dict:
    today = today or date.today()

    contract_value = D(project.get("contract_value_try"))

    # --- Budget (project level) ---
    revised_budget = money(
        D(project.get("original_budget_try")) + D(project.get("approved_variations_try"))
    )

    # --- Cost rollups (Section 7.1; CR-023 commitment relief) ---
    total_committed_gross = ZERO  # entry_type in (actual, committed), ex-VAT (legacy)
    total_actual = ZERO      # entry_type == actual, ex-VAT
    total_actual_with_vat = ZERO  # for the "Gerçekleşen Maliyet" hero card (Section 4.2)
    total_paid_out = ZERO    # amount_paid_try
    total_open_committed = ZERO  # CR-023: Σ open_commitment (committed − linked actuals)

    # CR-023: an actual linked to a commitment relieves it, so the open portion of
    # that commitment is netted out and the same money is never counted twice.
    relief = relief_by_commitment(cost_entries, "amount_try")

    for e in cost_entries:
        etype = e.get("entry_type", "actual")
        amt = D(e.get("amount_try"))
        if etype in ("actual", "committed"):
            total_committed_gross += amt
        if etype == "actual":
            total_actual += amt
            total_actual_with_vat += D(e.get("total_with_vat_try"))
        if etype == "committed":
            total_open_committed += open_commitment(e, relief, "amount_try")
        total_paid_out += D(e.get("amount_paid_try"))

    total_committed_gross = money(total_committed_gross)
    total_actual = money(total_actual)
    total_actual_with_vat = money(total_actual_with_vat)
    total_paid_out = money(total_paid_out)
    total_open_committed = money(total_open_committed)

    # Exposure = money already spent (actual) + money locked in but not yet billed
    # (open commitments). This REPLACES the old "actual + all committed" so a
    # commitment and its later invoice never both count (CR-023 §4).
    total_committed_exposure = money(total_actual + total_open_committed)
    remaining_budget = money(revised_budget - total_committed_exposure)

    # --- Per-category budget table (Section 4.3) ---
    categories = _compute_category_rows(
        cost_entries, budget_line_items, today, extra_category_keys, relief
    )
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
        # Legacy gross (actual + all committed) kept for back-compat consumers.
        "total_committed_try": total_committed_gross,
        # CR-023: relief-aware figures.
        "total_open_committed_try": total_open_committed,
        "total_committed_exposure_try": total_committed_exposure,
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
    cost_entries: list[dict],
    budget_line_items: list[dict],
    today: date,
    extra_category_keys: list[str] | None = None,
    relief: dict | None = None,
) -> list[dict]:
    """Budget-vs-actual rows per cost category (Section 4.3 / CR-002-A).

    All 15 standard categories are ALWAYS returned (even with no activity), plus
    any company custom categories (extra_category_keys) and any categories that
    appear in the data or budget rows.
    """
    budgets = {b["cost_category"]: b for b in budget_line_items}
    if relief is None:
        relief = relief_by_commitment(cost_entries, "amount_try")

    # Aggregate cost entries by category.
    agg: dict[str, dict] = {}
    for e in cost_entries:
        cat = e.get("cost_category")
        if cat is None:
            continue
        a = agg.setdefault(
            cat, {"committed": ZERO, "invoiced": ZERO, "paid": ZERO, "open_committed": ZERO}
        )
        etype = e.get("entry_type", "actual")
        amt = D(e.get("amount_try"))
        if etype in ("actual", "committed"):
            a["committed"] += amt
        if etype == "actual":
            a["invoiced"] += amt
        if etype == "committed":
            # CR-023: open = committed − linked actuals (never below 0).
            a["open_committed"] += open_commitment(e, relief, "amount_try")
        a["paid"] += D(e.get("amount_paid_try"))

    rows: list[dict] = []
    # CR-002-A: always include all 15 standard categories, plus custom categories,
    # plus any category present in budgets or cost data.
    all_cats = list(COST_CATEGORY_KEYS)
    for cat in (extra_category_keys or []):
        if cat not in all_cats:
            all_cats.append(cat)
    for cat in list(agg) + list(budgets):
        if cat not in all_cats:
            all_cats.append(cat)

    for cat in all_cats:
        b = budgets.get(cat, {})
        a = agg.get(cat, {"committed": ZERO, "invoiced": ZERO, "paid": ZERO, "open_committed": ZERO})
        original = D(b.get("original_budget_try"))
        variations = D(b.get("approved_variations_try"))
        revised = money(original + variations)
        committed = money(a["committed"])  # legacy gross (actual + committed)
        invoiced = money(a["invoiced"])
        open_committed = money(a["open_committed"])  # CR-023: açık taahhüt
        paid = money(a["paid"])
        # CR-023: exposure = actual + open committed; remaining nets BOTH out so a
        # commitment and its linked invoice never double-charge the budget.
        exposure = money(invoiced + open_committed)
        remaining = money(revised - exposure)
        pct_spent = pct(safe_div(invoiced, revised) * HUNDRED)

        forecast_raw = b.get("forecast_final_try")
        # Forecast falls back to max(revised budget, actual invoiced) when unset.
        forecast_base = money(forecast_raw) if forecast_raw is not None else money(max(revised, invoiced))
        # CR-023 §5.3: open commitments are money you WILL spend, so the forecast
        # is at least actual + open committed regardless of the budget-derived base.
        forecast = money(max(forecast_base, exposure))
        variance = money(forecast - revised)  # positive = over budget

        # CR-003-A: RAG dot rules.
        #   gray  -> no budget entered (revised == 0)
        #   red   -> over budget (% spent > 100) OR variance positive
        #   amber -> 85-100% spent
        #   green -> < 85% and variance <= 0
        if revised == ZERO:
            status = "gray"
        elif pct_spent > HUNDRED or variance > ZERO:
            status = "red"
        elif pct_spent >= Decimal("85"):
            status = "amber"
        else:
            status = "green"

        # CR-002-A: do NOT skip empty categories — all standard/custom categories
        # are always shown so the user can budget against them.

        rows.append(
            {
                "cost_category": cat,
                "original_budget_try": money(original),
                "approved_variations_try": money(variations),
                "revised_budget_try": revised,
                "committed_try": committed,
                # CR-023: açık taahhüt (committed minus linked actuals) + exposure.
                "open_committed_try": open_committed,
                "exposure_try": exposure,
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
