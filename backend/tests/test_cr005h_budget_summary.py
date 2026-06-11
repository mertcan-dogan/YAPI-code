"""CR-005-H: page-top budget summary (4 KPI cards + usage bar chart).

The summary band is rendered entirely from the existing budget table API — no new
endpoint. These tests pin that the API supplies what the KPI cards and the usage
chart read: portfolio totals and per-category pct_spent (incl. the over-budget
count).
"""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _budget(client, pid, category, amount):
    assert client.put(f"/api/v1/projects/{pid}/budget/{category}", json={"original_budget_try": amount}).status_code == 200


def _cost(client, pid, category, amount):
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2026-06-01", "cost_category": category, "amount_try": amount, "entry_type": "actual"},
    )
    assert r.status_code == 200, r.text


def test_budget_api_supplies_kpi_totals(client, seed):
    """The 4 KPI cards read totals.revised/committed/invoiced."""
    pid = _login(client, seed)
    _budget(client, pid, "material_steel", "100000")
    _budget(client, pid, "labour_direct", "200000")
    _cost(client, pid, "material_steel", "40000")

    totals = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]["totals"]
    assert totals["revised_budget_try"] == "300000.00"
    for key in ("committed_try", "invoiced_try", "paid_try", "remaining_try"):
        assert key in totals


def test_budget_api_supplies_over_budget_count(client, seed):
    """The 'Bütçe Aşımı Olan Kategoriler' card counts pct_spent > 100."""
    pid = _login(client, seed)
    _budget(client, pid, "material_steel", "100000")
    _budget(client, pid, "labour_direct", "100000")
    _cost(client, pid, "material_steel", "130000")   # 130% → over budget
    _cost(client, pid, "labour_direct", "50000")     # 50% → fine

    cats = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]["categories"]
    over = [c for c in cats if float(c["pct_spent"]) > 100]
    assert len(over) == 1
    assert over[0]["cost_category"] == "material_steel"


def test_chart_categories_have_pct_spent(client, seed):
    """Every budgeted category exposes the pct_spent the usage chart bars use."""
    pid = _login(client, seed)
    _budget(client, pid, "material_steel", "100000")
    cats = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]["categories"]
    budgeted = [c for c in cats if float(c["revised_budget_try"]) > 0]
    assert budgeted and all("pct_spent" in c for c in budgeted)
