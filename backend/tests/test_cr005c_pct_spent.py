"""CR-005-C: budget table '% Harcanan' column — value + colour thresholds.

The column shows (invoiced / revised) × 100 and colours it: <%85 normal,
%85–%100 amber, >%100 red. These tests pin the backend pct_spent/status that the
frontend colour rule reads.
"""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _budget(client, pid, category, amount):
    r = client.put(f"/api/v1/projects/{pid}/budget/{category}", json={"original_budget_try": amount})
    assert r.status_code == 200, r.text


def _cost(client, pid, category, amount):
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2026-06-01", "cost_category": category, "amount_try": amount, "entry_type": "actual"},
    )
    assert r.status_code == 200, r.text


def _row(client, pid, category):
    data = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    return next(c for c in data["categories"] if c["cost_category"] == category)


def test_pct_spent_amber_band(client, seed):
    """90% spent → amber band (>=85, <=100)."""
    pid = _login(client, seed)
    _budget(client, pid, "material_steel", "100000")
    _cost(client, pid, "material_steel", "90000")
    row = _row(client, pid, "material_steel")
    assert float(row["pct_spent"]) == 90.0
    assert row["status"] == "amber"


def test_pct_spent_over_100_red(client, seed):
    """120% spent → over budget, red."""
    pid = _login(client, seed)
    _budget(client, pid, "labour_direct", "100000")
    _cost(client, pid, "labour_direct", "120000")
    row = _row(client, pid, "labour_direct")
    assert float(row["pct_spent"]) == 120.0
    assert row["status"] == "red"


def test_pct_spent_below_85_normal(client, seed):
    """50% spent → normal/green band."""
    pid = _login(client, seed)
    _budget(client, pid, "subcontractor", "100000")
    _cost(client, pid, "subcontractor", "50000")
    row = _row(client, pid, "subcontractor")
    assert float(row["pct_spent"]) == 50.0
    assert row["status"] == "green"
