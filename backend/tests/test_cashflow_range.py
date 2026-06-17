"""Cashflow date-range filter + opening-balance carry.

Engine tests assert exact month windows + carried-in cumulative deterministically
(fixed `today`); API tests cover param validation, the opening-balance meta, and
no-regression when the params are omitted.
"""
from datetime import date
from decimal import Decimal

from app.calculations import compute_monthly_cashflow, opening_balance
from app.constants import ROLE_DIRECTOR

TODAY = date(2025, 6, 15)


def _costs():
    # Jan -100k, Feb -50k (actual outflows, all past relative to TODAY).
    return [
        {"total_with_vat_try": Decimal("100000"), "entry_date": date(2025, 1, 10), "payment_status": "unpaid"},
        {"total_with_vat_try": Decimal("50000"), "entry_date": date(2025, 2, 10), "payment_status": "unpaid"},
    ]


def _invoices():
    # Mar +200k actual inflow.
    return [
        {"amount_received_try": Decimal("200000"), "date_received": date(2025, 3, 10), "payment_status": "paid"},
    ]


# --------------------------------------------------------------------------- #
# Engine: explicit range + opening-balance carry
# --------------------------------------------------------------------------- #
def test_range_returns_exactly_requested_months():
    rows = compute_monthly_cashflow(_costs(), _invoices(), today=TODAY,
                                    from_month="2025-03", to_month="2025-05")
    assert [r["month"] for r in rows] == ["2025-03", "2025-04", "2025-05"]


def test_opening_balance_carry_seeds_cumulative_not_zero():
    # Flows before March net to -150,000 (Jan -100k, Feb -50k).
    assert opening_balance(_costs(), _invoices(), "2025-03", today=TODAY) == Decimal("-150000.00")
    rows = compute_monthly_cashflow(_costs(), _invoices(), today=TODAY,
                                    from_month="2025-03", to_month="2025-05")
    by = {r["month"]: r for r in rows}
    # March net +200k on top of the -150k carried in -> +50k (NOT +200k).
    assert by["2025-03"]["cumulative_try"] == Decimal("50000.00")
    assert by["2025-04"]["cumulative_try"] == Decimal("50000.00")


def test_range_at_history_start_has_zero_opening():
    assert opening_balance(_costs(), _invoices(), "2025-01", today=TODAY) == Decimal("0.00")
    rows = compute_monthly_cashflow(_costs(), _invoices(), today=TODAY,
                                    from_month="2025-01", to_month="2025-02")
    by = {r["month"]: r for r in rows}
    assert by["2025-01"]["cumulative_try"] == Decimal("-100000.00")
    assert by["2025-02"]["cumulative_try"] == Decimal("-150000.00")


def test_ranged_cumulative_matches_full_timeline_at_same_month():
    """The carried-in design means a month's cumulative is identical whether viewed
    in the full window or a custom range starting later."""
    full = {r["month"]: r for r in compute_monthly_cashflow(_costs(), _invoices(), today=TODAY)}
    ranged = {r["month"]: r for r in compute_monthly_cashflow(
        _costs(), _invoices(), today=TODAY, from_month="2025-03", to_month="2025-04")}
    assert full["2025-03"]["cumulative_try"] == ranged["2025-03"]["cumulative_try"]
    assert full["2025-04"]["cumulative_try"] == ranged["2025-04"]["cumulative_try"]


def test_omitting_range_is_identical_to_default():
    base = compute_monthly_cashflow(_costs(), _invoices(), today=TODAY)
    same = compute_monthly_cashflow(_costs(), _invoices(), today=TODAY, from_month=None, to_month=None)
    assert base == same
    assert len(base) == 18  # fixed rolling window, cumulative starts at 0
    assert base[0]["cumulative_try"] == Decimal("0.00")


# --------------------------------------------------------------------------- #
# API: validation + opening-balance meta + carry end-to-end
# --------------------------------------------------------------------------- #
def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _add_cost(client, pid, entry_date, amount):
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": entry_date, "cost_category": "other", "amount_try": amount, "vat_rate": "0",
    })
    assert r.status_code == 200, r.text


def test_api_range_returns_requested_window(client, seed):
    pid = _login(client, seed)
    _add_cost(client, pid, "2025-03-10", "100000")  # twv 100000 (vat 0)
    r = client.get(f"/api/v1/projects/{pid}/cashflow", params={"from_month": "2025-03", "to_month": "2025-04"})
    assert r.status_code == 200, r.text
    months = [row["month"] for row in r.json()["data"]]
    assert months == ["2025-03", "2025-04"]
    meta = r.json()["meta"]
    assert meta["opening_balance_try"] == "0.00"  # nothing before March
    assert meta["from_month"] == "2025-03" and meta["to_month"] == "2025-04"


def test_api_opening_balance_carries_into_later_range(client, seed):
    pid = _login(client, seed)
    _add_cost(client, pid, "2025-03-10", "100000")
    # A range that STARTS after the cost must carry the -100,000 in, not restart at 0.
    r = client.get(f"/api/v1/projects/{pid}/cashflow", params={"from_month": "2025-04", "to_month": "2025-05"})
    data = r.json()["data"]
    meta = r.json()["meta"]
    assert meta["opening_balance_try"] == "-100000.00"
    assert {row["month"]: row["cumulative_try"] for row in data} == {
        "2025-04": "-100000.00", "2025-05": "-100000.00",
    }


def test_api_no_params_is_no_regression(client, seed):
    pid = _login(client, seed)
    r = client.get(f"/api/v1/projects/{pid}/cashflow")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 18  # fixed rolling window unchanged
    meta = r.json()["meta"]
    assert meta["opening_balance_try"] == "0.00"
    assert meta["from_month"] is None and meta["to_month"] is None
    assert "usd" in meta  # existing meta preserved


def test_api_from_after_to_is_422(client, seed):
    pid = _login(client, seed)
    r = client.get(f"/api/v1/projects/{pid}/cashflow", params={"from_month": "2025-06", "to_month": "2025-03"})
    assert r.status_code == 422
    assert "sonra olamaz" in r.json()["error"]["message"].lower()


def test_api_invalid_month_is_422(client, seed):
    pid = _login(client, seed)
    r = client.get(f"/api/v1/projects/{pid}/cashflow", params={"from_month": "2025-13", "to_month": "2025-14"})
    assert r.status_code == 422


def test_api_partial_range_is_422(client, seed):
    pid = _login(client, seed)
    r = client.get(f"/api/v1/projects/{pid}/cashflow", params={"from_month": "2025-03"})
    assert r.status_code == 422
