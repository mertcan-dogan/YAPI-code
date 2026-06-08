"""CR-001-E: equipment auto-creates a committed cost_entry when opted in."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _equipment(**over):
    base = {
        "equipment_name": "Ekskavatör",
        "ownership_type": "rented",
        "supplier_name": "Kiralama A.Ş.",
        "rate_try": "1000",
        "rate_unit": "day",
        "deployment_start": "2025-03-01",
        "deployment_end": "2025-03-11",  # 10 days
        "fuel_maintenance_try": "500",
    }
    base.update(over)
    return base


def test_equipment_with_budget_creates_cost_entry(client, seed):
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/equipment", json=_equipment(add_to_budget=True))
    assert r.status_code == 200, r.text

    costs = client.get(f"/api/v1/projects/{pid}/costs").json()["data"]
    auto = [c for c in costs if "otomatik oluşturuldu" in (c["description"] or "")]
    assert len(auto) == 1
    entry = auto[0]
    # CR-002-E: inclusive days = (11-1)+1 = 11; 11*1000 + 500 fuel = 11,500; vat 20%.
    assert entry["amount_try"] == "11500.00"
    assert entry["total_with_vat_try"] == "13800.00"
    assert entry["cost_category"] == "equipment_rented"
    assert entry["entry_type"] == "committed"
    assert entry["supplier_name"] == "Kiralama A.Ş."


def test_equipment_without_budget_creates_no_cost_entry(client, seed):
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/equipment", json=_equipment(add_to_budget=False))
    assert r.status_code == 200, r.text
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()["data"]
    assert costs == [] or all("otomatik oluşturuldu" not in (c["description"] or "") for c in costs)


def test_equipment_owned_uses_owned_category(client, seed):
    pid = _login(client, seed)
    r = client.post(
        f"/api/v1/projects/{pid}/equipment",
        json=_equipment(ownership_type="owned", rate_try=None, fuel_maintenance_try="2000", add_to_budget=True),
    )
    assert r.status_code == 200, r.text
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()["data"]
    auto = [c for c in costs if "otomatik oluşturuldu" in (c["description"] or "")]
    assert auto[0]["cost_category"] == "equipment_owned"
    assert auto[0]["amount_try"] == "2000.00"  # owned -> fuel/maintenance only
