"""CR-005-F: reminders time filter.

The "Tümü" button moves to the front of the Zaman row (frontend ordering). The
time buckets it drives — Tümü / Vadesi Geçmiş / Bugün / 7 / 30 / 60 — classify
items by the endpoint's signed `days_remaining`. These tests pin that contract so
the bucketing stays correct.
"""
from datetime import date, timedelta

from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _cost(client, pid, due_date, amount="10000"):
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2026-01-01", "cost_category": "other", "amount_try": amount,
              "vat_rate": "0", "payment_due_date": due_date.isoformat()},
    )
    assert r.status_code == 200, r.text


def test_reminders_days_remaining_sign_drives_time_buckets(client, seed):
    pid = _login(client, seed)
    today = date.today()
    _cost(client, pid, today - timedelta(days=3))   # overdue
    _cost(client, pid, today)                        # today
    _cost(client, pid, today + timedelta(days=5))    # within 7

    items = client.get("/api/v1/reminders").json()["data"]
    by_days = sorted(i["days_remaining"] for i in items)
    assert -3 in by_days   # "Vadesi Geçmiş" bucket (d < 0)
    assert 0 in by_days    # "Bugün" bucket (d == 0)
    assert 5 in by_days    # "7 Gün" bucket (0 <= d <= 7)
    # Every reminder carries the fields the Tür + Zaman filters read.
    for i in items:
        assert i["kind"] in ("payable", "receivable")
        assert "amount_try" in i


def test_reminders_all_returns_every_item(client, seed):
    """The default 'Tümü' selection must surface all reminders regardless of timing."""
    pid = _login(client, seed)
    today = date.today()
    _cost(client, pid, today - timedelta(days=90))   # far overdue
    _cost(client, pid, today + timedelta(days=200))  # far future

    items = client.get("/api/v1/reminders").json()["data"]
    assert len(items) >= 2
