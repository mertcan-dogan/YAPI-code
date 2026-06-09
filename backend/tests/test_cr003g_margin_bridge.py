"""CR-003-G: margin bridge components."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_margin_bridge_in_dashboard(client, seed):
    pid = _login(client, seed)
    b = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["margin_bridge"]
    for key in ("original_margin_try", "approved_variations_try", "pending_variations_try",
                "cost_overruns_try", "cost_savings_try", "current_margin_try"):
        assert key in b


def test_overrun_and_saving_components(client, seed):
    pid = _login(client, seed)
    # One category over budget (overrun), one under (saving).
    client.put(f"/api/v1/projects/{pid}/budget/material_concrete", json={"original_budget_try": "100000", "forecast_final_try": "130000"})
    client.put(f"/api/v1/projects/{pid}/budget/labour_direct", json={"original_budget_try": "100000", "forecast_final_try": "80000"})
    b = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["margin_bridge"]
    # overrun: 130k-100k = 30k -> reported negative
    assert b["cost_overruns_try"] == "-30000.00"
    # saving: 100k-80k = 20k -> reported positive
    assert b["cost_savings_try"] == "20000.00"
