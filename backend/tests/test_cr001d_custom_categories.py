"""CR-001-D: custom cost categories."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])


def test_create_and_list_custom_category(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/custom-categories", json={"name": "Nakliye"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"] == "Nakliye"
    assert r.json()["data"]["usage_count"] == 1

    lst = client.get("/api/v1/custom-categories").json()["data"]
    assert any(c["name"] == "Nakliye" for c in lst)


def test_duplicate_increments_usage_count(client, seed):
    _login(client, seed)
    client.post("/api/v1/custom-categories", json={"name": "Güvenlik"})
    r2 = client.post("/api/v1/custom-categories", json={"name": "  güvenlik "})  # same normalized
    assert r2.json()["data"]["usage_count"] == 2
    # Only one row exists.
    lst = client.get("/api/v1/custom-categories").json()["data"]
    assert len([c for c in lst if c["name"].lower() == "güvenlik"]) == 1


def test_custom_categories_are_company_scoped(client, seed):
    _login(client, seed)
    client.post("/api/v1/custom-categories", json={"name": "ŞirketA-Özel"})
    # Company B must not see it.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    lst = client.get("/api/v1/custom-categories").json()["data"]
    assert all(c["name"] != "ŞirketA-Özel" for c in lst)


def test_cost_entry_accepts_custom_category_and_bumps_usage(client, seed):
    _login(client, seed)
    pid = seed["a"]["project"].id
    client.post("/api/v1/custom-categories", json={"name": "Nakliye"})
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2025-03-01", "cost_category": "Nakliye", "amount_try": "5000"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["cost_category"] == "Nakliye"
    # usage_count bumped from 1 (create) to 2 (used on a cost entry).
    lst = client.get("/api/v1/custom-categories").json()["data"]
    nakliye = next(c for c in lst if c["name"] == "Nakliye")
    assert nakliye["usage_count"] == 2
