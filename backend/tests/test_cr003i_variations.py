"""CR-003-I: variations / Ek İş module."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _variation(**over):
    base = {"variation_number": "EK-001", "title": "İlave kazı", "submitted_date": "2026-03-01",
            "value_try": "200000", "cost_impact_try": "50000", "status": "pending"}
    base.update(over)
    return base


def test_create_and_list_variation_with_summary(client, seed):
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/variations", json=_variation())
    assert r.status_code == 200, r.text
    body = client.get(f"/api/v1/projects/{pid}/variations").json()
    assert body["meta"]["total_requested"] == "200000.00"
    assert body["meta"]["pending"] == "200000.00"


def test_margin_impact_computed(client, seed):
    pid = _login(client, seed)
    v = client.post(f"/api/v1/projects/{pid}/variations", json=_variation(
        status="approved", approved_date="2026-03-10", approved_value_try="180000", cost_impact_try="60000",
    )).json()["data"]
    # margin impact = approved 180000 - cost 60000 = 120000
    assert v["margin_impact_try"] == "120000.00"


def test_approval_updates_budget(client, seed):
    pid = _login(client, seed)
    client.post(f"/api/v1/projects/{pid}/variations", json=_variation(
        cost_category="material_concrete", status="approved", approved_date="2026-03-10", approved_value_try="150000",
    ))
    # The concrete budget line's approved_variations flows into revised budget.
    budget = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    concrete = next(c for c in budget["categories"] if c["cost_category"] == "material_concrete")
    assert concrete["approved_variations_try"] == "150000.00"
    assert concrete["revised_budget_try"] == "150000.00"


def test_pending_variation_does_not_update_budget(client, seed):
    pid = _login(client, seed)
    client.post(f"/api/v1/projects/{pid}/variations", json=_variation(cost_category="material_steel", status="pending"))
    budget = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    steel = next(c for c in budget["categories"] if c["cost_category"] == "material_steel")
    assert steel["approved_variations_try"] == "0.00"
