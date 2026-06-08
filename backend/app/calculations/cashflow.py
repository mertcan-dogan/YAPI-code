"""Monthly cash flow calculation (Section 7.2).

Rolling window of months. For each month:
  Planned Outflows : SUM cost_entries.amount_try WHERE entry_type=forecast
                     AND entry_date in month
  Actual Outflows  : SUM cost_entries.amount_paid_try WHERE date_paid in month
  Planned Inflows  : SUM client_invoices.net_due_try WHERE due_date in month
  Actual Inflows   : SUM client_invoices.amount_received_try
                     WHERE date_received in month

Past months use actuals, future months use planned, current month uses
actuals-to-date. The cumulative column is a running total from the window
start (Section 4.6).
"""
from datetime import date
from decimal import Decimal

from app.calculations.money import D, money

ZERO = Decimal("0")


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def build_month_window(window: int = 18, anchor: date | None = None, back: int = 6) -> list[tuple[int, int]]:
    """Return (year, month) tuples spanning `back` months before the anchor
    through the remainder of the window (default 18 months, 6 back / 12 fwd)."""
    anchor = anchor or date.today()
    start_y, start_m = _add_months(anchor.year, anchor.month, -back)
    return [_add_months(start_y, start_m, i) for i in range(window)]


def compute_monthly_cashflow(
    cost_entries: list[dict],
    client_invoices: list[dict],
    today: date | None = None,
    window: int = 18,
    back: int = 6,
) -> list[dict]:
    today = today or date.today()
    current_key = _month_key(today)
    months = build_month_window(window=window, anchor=today, back=back)

    # Bucket sums by month key (CR-002-B).
    planned_out: dict[str, Decimal] = {}
    actual_out: dict[str, Decimal] = {}
    planned_in: dict[str, Decimal] = {}
    actual_in: dict[str, Decimal] = {}

    for e in cost_entries:
        # Actual outflow: a cost is realised when the invoice is dated (entry_date),
        # regardless of whether it has been paid yet — uses total incl. VAT.
        if e.get("entry_date"):
            k = _month_key(e["entry_date"])
            actual_out[k] = actual_out.get(k, ZERO) + D(e.get("total_with_vat_try"))
        # Planned outflow: still-unpaid costs land in their payment_due_date month.
        if e.get("payment_due_date") and e.get("payment_status") == "unpaid":
            k = _month_key(e["payment_due_date"])
            planned_out[k] = planned_out.get(k, ZERO) + D(e.get("total_with_vat_try"))

    for inv in client_invoices:
        # Actual inflow: money actually collected, in its date_received month.
        if inv.get("date_received"):
            k = _month_key(inv["date_received"])
            actual_in[k] = actual_in.get(k, ZERO) + D(inv.get("amount_received_try"))
        # Planned inflow: still-unpaid invoices land in their due_date month.
        if inv.get("due_date") and inv.get("payment_status") == "unpaid":
            k = _month_key(inv["due_date"])
            planned_in[k] = planned_in.get(k, ZERO) + D(inv.get("net_due_try"))

    rows: list[dict] = []
    cumulative = ZERO
    for (y, m) in months:
        k = f"{y:04d}-{m:02d}"
        p_out = money(planned_out.get(k, ZERO))
        a_out = money(actual_out.get(k, ZERO))
        p_in = money(planned_in.get(k, ZERO))
        a_in = money(actual_in.get(k, ZERO))

        is_past = k < current_key
        is_current = k == current_key

        # Effective figures: actuals for past/current, planned for future.
        if is_past or is_current:
            eff_out = a_out
            eff_in = a_in
        else:
            eff_out = p_out
            eff_in = p_in

        net = money(eff_in - eff_out)
        cumulative = money(cumulative + net)

        rows.append(
            {
                "month": k,
                "year": y,
                "month_num": m,
                "planned_out_try": p_out,
                "actual_out_try": a_out,
                "planned_in_try": p_in,
                "actual_in_try": a_in,
                "net_try": net,
                "cumulative_try": cumulative,
                "is_past": is_past,
                "is_current": is_current,
            }
        )
    return rows
