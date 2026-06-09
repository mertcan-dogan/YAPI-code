"""CR-003-F: Forecast-at-Completion."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_fac_in_dashboard(client, seed):
    pid = _login(client, seed)
    # Set budgets + a forecast and add an actual cost.
    client.put(f"/api/v1/projects/{pid}/budget/material_concrete", json={"original_budget_try": "400000", "forecast_final_try": "450000"})
    client.put(f"/api/v1/projects/{pid}/budget/labour_direct", json={"original_budget_try": "300000"})
    client.post(f"/api/v1/projects/{pid}/costs", json={"entry_date": "2026-03-01", "cost_category": "material_concrete", "amount_try": "100000", "vat_rate": "20"})

    fac = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["forecast_at_completion"]
    # original = 400k + 300k = 700k
    assert fac["original_budget_try"] == "700000.00"
    # cost to date = 100k * 1.20 = 120k (VAT inclusive)
    assert fac["cost_to_date_try"] == "120000.00"
    # forecast final = concrete forecast 450k + labour (no forecast, no actual) 0 = 450k
    assert fac["forecast_final_cost_try"] == "450000.00"
    # cost to complete = 450k - 120k = 330k
    assert fac["cost_to_complete_try"] == "330000.00"
    # margin = (contract 1,000,000 - 450,000)/1,000,000 = 55%
    assert fac["forecast_final_margin_pct"] == "55.00"


def test_fac_over_budget_flag(client, seed):
    pid = _login(client, seed)
    client.put(f"/api/v1/projects/{pid}/budget/material_steel", json={"original_budget_try": "100000", "forecast_final_try": "150000"})
    fac = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["forecast_at_completion"]
    assert fac["over_budget"] is True


def test_ai_narrative_endpoint(client, seed):
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/ai-narrative")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["narrative"]  # non-empty (graceful fallback when no API key)
    assert "generated_at" in data
