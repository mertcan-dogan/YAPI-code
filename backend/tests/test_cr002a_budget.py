"""CR-002-A: all 15 categories always shown, editable revised budget, totals."""
from app.constants import COST_CATEGORY_KEYS, ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_all_15_categories_shown_without_costs(client, seed):
    pid = _login(client, seed)
    data = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    keys = {c["cost_category"] for c in data["categories"]}
    for k in COST_CATEGORY_KEYS:
        assert k in keys, f"missing category {k}"
    # Empty category (no budget) shows zeros + gray status (CR-003-A).
    steel = next(c for c in data["categories"] if c["cost_category"] == "material_steel")
    assert steel["committed_try"] == "0.00"
    assert steel["status"] == "gray"


def test_revised_budget_editable_and_flows_to_table(client, seed):
    pid = _login(client, seed)
    r = client.put(f"/api/v1/projects/{pid}/budget/material_steel", json={"original_budget_try": "500000", "approved_variations_try": "0"})
    assert r.status_code == 200, r.text
    data = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    steel = next(c for c in data["categories"] if c["cost_category"] == "material_steel")
    assert steel["revised_budget_try"] == "500000.00"
    assert steel["remaining_try"] == "500000.00"  # no commitments yet
    assert steel["pct_spent"] == "0.00"


def test_budget_totals_row(client, seed):
    pid = _login(client, seed)
    client.put(f"/api/v1/projects/{pid}/budget/material_steel", json={"original_budget_try": "300000"})
    client.put(f"/api/v1/projects/{pid}/budget/labour_direct", json={"original_budget_try": "200000"})
    data = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    assert data["totals"]["revised_budget_try"] == "500000.00"


def test_budget_edit_writes_audit_log(client, seed, db):
    from app.models.audit_log import AuditLog

    pid = _login(client, seed)
    client.put(f"/api/v1/projects/{pid}/budget/material_steel", json={"original_budget_try": "123000"})
    rows = db.query(AuditLog).filter(AuditLog.table_name == "budget_line_items").all()
    assert len(rows) >= 1


def test_custom_category_appears_in_budget(client, seed):
    pid = _login(client, seed)
    client.post("/api/v1/custom-categories", json={"name": "Nakliye"})
    data = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    labels = {c["cost_category"] for c in data["categories"]}
    assert "Nakliye" in labels
