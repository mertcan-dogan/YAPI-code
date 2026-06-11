"""CR-005-B: Budget category drawer — trend chart data + ₺ currency.

Root cause of the empty trend chart: the drawer requested per_page=200 from the
costs endpoint, which caps per_page at 100 → FastAPI returned 422, the frontend
swallowed it and rendered an empty axis. These tests pin the data contract the
drawer relies on (category filter + the 100 cap) so the regression can't return.
"""
from app.constants import ROLE_DIRECTOR


def _make_cost(client, pid, category, amount, date="2026-06-01"):
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": date, "cost_category": category, "amount_try": amount, "vat_rate": "20"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_costs_endpoint_filters_by_category_for_drawer(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    _make_cost(client, pid, "material_concrete", "100000")
    _make_cost(client, pid, "material_concrete", "50000")
    _make_cost(client, pid, "labor", "30000")

    r = client.get(f"/api/v1/projects/{pid}/costs", params={"category": "material_concrete", "per_page": 100})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 2
    assert {c["cost_category"] for c in data} == {"material_concrete"}


def test_costs_endpoint_per_page_capped_at_100(client, seed):
    """The drawer must request <=100; 200 is rejected (the original bug)."""
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    assert client.get(f"/api/v1/projects/{pid}/costs", params={"per_page": 200}).status_code == 422
    assert client.get(f"/api/v1/projects/{pid}/costs", params={"per_page": 100}).status_code == 200
