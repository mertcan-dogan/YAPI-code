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

CR-057 — each month also carries a USD-at-date companion (``*_usd``): the USD of
the EXACT ₺ cash amount, ``₺_amount ÷ row.fx_rate_usd`` (rate-at-date,
VAT-inclusive — the USD of the real money moved, cash-basis; this INTENTIONALLY
differs from the ex-VAT accrual ``amount_usd`` snapshots). It is purely additive:
the ₺ output is byte-identical whether or not a row carries a rate. A contributing
row with a null/invalid ``fx_rate_usd`` POISONS that bucket's USD to ``None`` (→
renders "–"), never a partial sum; the cumulative USD poisons to ``None`` once any
month in its running total is ``None``.
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


def _month_range(from_month: str, to_month: str) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) from from_month..to_month (both YYYY-MM)."""
    fy, fm = (int(x) for x in from_month.split("-"))
    ty, tm = (int(x) for x in to_month.split("-"))
    start, end = fy * 12 + (fm - 1), ty * 12 + (tm - 1)
    return [(idx // 12, idx % 12 + 1) for idx in range(start, end + 1)]


def _money_or_none(x):
    """``money(x)`` or ``None`` — carries a poisoned USD bucket ("–") through the
    same 2dp quantize the ₺ side uses."""
    return None if x is None else money(x)


def _build_buckets(cost_entries: list[dict], client_invoices: list[dict]):
    """Sum flows into per-month buckets (CR-002-B).

    Returns ``(try_buckets, usd_buckets, usd_missing)``:
      * ``try_buckets`` — the 4 ₺ dicts (planned_out, actual_out, planned_in, actual_in);
        byte-identical to pre-CR-057.
      * ``usd_buckets`` — the 4 parallel USD dicts (CR-057). Each month value is a
        running ``Σ(₺ ÷ rate)`` Decimal, OR ``None`` once a non-zero contribution had a
        null/invalid rate (poisoned — never a partial sum).
      * ``usd_missing`` — per-month count of null-rate non-zero contributions (a warning
        signal; a month with any such contribution renders its USD as "–").
    """
    planned_out: dict[str, Decimal] = {}
    actual_out: dict[str, Decimal] = {}
    planned_in: dict[str, Decimal] = {}
    actual_in: dict[str, Decimal] = {}
    planned_out_usd: dict[str, Decimal | None] = {}
    actual_out_usd: dict[str, Decimal | None] = {}
    planned_in_usd: dict[str, Decimal | None] = {}
    actual_in_usd: dict[str, Decimal | None] = {}
    usd_missing: dict[str, int] = {}

    def _add_usd(bucket: dict, k: str, amount_try, rate) -> None:
        # USD-at-date of the exact ₺ cash amount (÷ rate). A zero-amount flow contributes
        # 0 USD regardless of rate (no poison — the complete sum is unaffected). A
        # null/invalid rate on a NON-zero flow poisons the bucket to None (→ "–") AND is
        # counted — the rate check runs before the already-poisoned short-circuit so
        # EVERY unrated non-zero row is counted, not just the first (usd_missing is an
        # honest per-row count, order-independent).
        amt = D(amount_try)
        if amt == ZERO:
            return
        if rate is None or D(rate) <= ZERO:
            usd_missing[k] = usd_missing.get(k, 0) + 1
            bucket[k] = None
            return
        if bucket.get(k, ZERO) is None:
            return  # already poisoned by an unrated row — a valid rate never un-poisons
        bucket[k] = bucket.get(k, ZERO) + amt / D(rate)

    for e in cost_entries:
        rate = e.get("fx_rate_usd")
        # Actual outflow: a cost is realised when the invoice is dated (entry_date),
        # regardless of whether it has been paid yet — uses total incl. VAT.
        if e.get("entry_date"):
            k = _month_key(e["entry_date"])
            amt = D(e.get("total_with_vat_try"))
            actual_out[k] = actual_out.get(k, ZERO) + amt
            _add_usd(actual_out_usd, k, amt, rate)
        # Planned outflow: still-unpaid costs land in their payment_due_date month.
        if e.get("payment_due_date") and e.get("payment_status") == "unpaid":
            k = _month_key(e["payment_due_date"])
            amt = D(e.get("total_with_vat_try"))
            planned_out[k] = planned_out.get(k, ZERO) + amt
            _add_usd(planned_out_usd, k, amt, rate)
    for inv in client_invoices:
        rate = inv.get("fx_rate_usd")
        # Actual inflow: money actually collected, in its date_received month.
        if inv.get("date_received"):
            k = _month_key(inv["date_received"])
            amt = D(inv.get("amount_received_try"))
            actual_in[k] = actual_in.get(k, ZERO) + amt
            _add_usd(actual_in_usd, k, amt, rate)
        # Planned inflow: still-unpaid invoices land in their due_date month.
        if inv.get("due_date") and inv.get("payment_status") == "unpaid":
            k = _month_key(inv["due_date"])
            amt = D(inv.get("net_due_try"))
            planned_in[k] = planned_in.get(k, ZERO) + amt
            _add_usd(planned_in_usd, k, amt, rate)
    return (
        (planned_out, actual_out, planned_in, actual_in),
        (planned_out_usd, actual_out_usd, planned_in_usd, actual_in_usd),
        usd_missing,
    )


def _eff_month(try_buckets, usd_buckets, k: str, current_key: str) -> dict:
    """Effective figures for month key ``k``: actuals for past/current, planned
    for future (relative to current_key). Carries the parallel USD-at-date figures
    (``*_usd``/``net_usd``), each ``None`` when its bucket was poisoned by a missing
    rate."""
    planned_out, actual_out, planned_in, actual_in = try_buckets
    po_u, ao_u, pi_u, ai_u = usd_buckets
    p_out = money(planned_out.get(k, ZERO))
    a_out = money(actual_out.get(k, ZERO))
    p_in = money(planned_in.get(k, ZERO))
    a_in = money(actual_in.get(k, ZERO))
    p_out_u = _money_or_none(po_u.get(k, ZERO))
    a_out_u = _money_or_none(ao_u.get(k, ZERO))
    p_in_u = _money_or_none(pi_u.get(k, ZERO))
    a_in_u = _money_or_none(ai_u.get(k, ZERO))
    is_past = k < current_key
    is_current = k == current_key
    if is_past or is_current:
        eff_out, eff_in = a_out, a_in
        eff_out_u, eff_in_u = a_out_u, a_in_u
    else:
        eff_out, eff_in = p_out, p_in
        eff_out_u, eff_in_u = p_out_u, p_in_u
    net_usd = None if (eff_in_u is None or eff_out_u is None) else money(eff_in_u - eff_out_u)
    return {
        "planned_out_try": p_out, "actual_out_try": a_out,
        "planned_in_try": p_in, "actual_in_try": a_in,
        "net_try": money(eff_in - eff_out), "is_past": is_past, "is_current": is_current,
        "planned_out_usd": p_out_u, "actual_out_usd": a_out_u,
        "planned_in_usd": p_in_u, "actual_in_usd": a_in_u,
        "net_usd": net_usd,
    }


def opening_balance(
    cost_entries: list[dict], client_invoices: list[dict], before_month: str, today: date | None = None
) -> Decimal:
    """Carried-in cumulative position: the net of ALL flows dated BEFORE
    ``before_month`` (YYYY-MM), using the same actuals/planned rule as the table.

    This seeds the cumulative line for a custom range so it does not misleadingly
    restart at zero mid-history. Exact Decimal; pure Python (dialect-safe).
    """
    today = today or date.today()
    current_key = _month_key(today)
    try_b, usd_b, _ = _build_buckets(cost_entries, client_invoices)
    keys = set().union(*(set(b) for b in try_b)) if any(try_b) else set()
    total = ZERO
    for k in keys:
        if k < before_month:
            total += _eff_month(try_b, usd_b, k, current_key)["net_try"]
    return money(total)


def opening_balance_usd(
    cost_entries: list[dict], client_invoices: list[dict], before_month: str, today: date | None = None
) -> Decimal | None:
    """CR-057 — the USD-at-date carried-in position: the net USD of all flows dated
    BEFORE ``before_month`` (mirrors ``opening_balance``). Returns ``None`` if ANY
    contributing month's net USD is ``None`` (a missing rate before the window means
    the seeded cumulative USD can't be stated → "–"), never a partial seed."""
    today = today or date.today()
    current_key = _month_key(today)
    try_b, usd_b, _ = _build_buckets(cost_entries, client_invoices)
    keys = set().union(*(set(b) for b in try_b)) if any(try_b) else set()
    total = ZERO
    for k in keys:
        if k < before_month:
            nu = _eff_month(try_b, usd_b, k, current_key)["net_usd"]
            if nu is None:
                return None
            total += nu
    return money(total)


def compute_monthly_cashflow(
    cost_entries: list[dict],
    client_invoices: list[dict],
    today: date | None = None,
    window: int = 18,
    back: int = 6,
    from_month: str | None = None,
    to_month: str | None = None,
) -> list[dict]:
    """Per-month cashflow rows with a running cumulative.

    Default (no from/to): the fixed rolling window (``back`` months back + the
    remainder of ``window``), cumulative starting at 0 — unchanged behavior.
    With from_month/to_month: exactly those months, and the cumulative is SEEDED
    with the opening balance (net of all flows before from_month) so the period's
    cumulative line is accurate rather than restarting at zero.

    CR-057 — each row also carries the USD-at-date companion (``planned_out_usd``,
    ``actual_out_usd``, ``planned_in_usd``, ``actual_in_usd``, ``net_usd``,
    ``cumulative_usd``) plus ``usd_missing`` (count of null-rate contributions that
    month). USD is additive-only; the ₺ fields are byte-identical.
    """
    today = today or date.today()
    current_key = _month_key(today)
    try_b, usd_b, usd_missing = _build_buckets(cost_entries, client_invoices)

    if from_month and to_month:
        months = _month_range(from_month, to_month)
        cumulative = opening_balance(cost_entries, client_invoices, from_month, today=today)
        cumulative_usd = opening_balance_usd(cost_entries, client_invoices, from_month, today=today)
    else:
        months = build_month_window(window=window, anchor=today, back=back)
        cumulative = ZERO
        cumulative_usd = ZERO

    rows: list[dict] = []
    for (y, m) in months:
        k = f"{y:04d}-{m:02d}"
        e = _eff_month(try_b, usd_b, k, current_key)
        cumulative = money(cumulative + e["net_try"])
        # Cumulative USD poisons to None once any month in the running total is None —
        # a partial cumulative USD would misstate the position, so it degrades to "–".
        if cumulative_usd is None or e["net_usd"] is None:
            cumulative_usd = None
        else:
            cumulative_usd = money(cumulative_usd + e["net_usd"])
        rows.append(
            {
                "month": k,
                "year": y,
                "month_num": m,
                "planned_out_try": e["planned_out_try"],
                "actual_out_try": e["actual_out_try"],
                "planned_in_try": e["planned_in_try"],
                "actual_in_try": e["actual_in_try"],
                "net_try": e["net_try"],
                "cumulative_try": cumulative,
                "is_past": e["is_past"],
                "is_current": e["is_current"],
                # CR-057 — USD-at-date companion (None → "–" when a rate is missing).
                "planned_out_usd": e["planned_out_usd"],
                "actual_out_usd": e["actual_out_usd"],
                "planned_in_usd": e["planned_in_usd"],
                "actual_in_usd": e["actual_in_usd"],
                "net_usd": e["net_usd"],
                "cumulative_usd": cumulative_usd,
                "usd_missing": usd_missing.get(k, 0),
            }
        )
    return rows
