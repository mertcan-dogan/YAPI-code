"""CR-001-G: edit/revert across entities + template auth."""
from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER


def _add_cost(client, pid, **over):
    body = {"entry_date": "2025-03-01", "cost_category": "other", "amount_try": "1000"}
    body.update(over)
    return client.post(f"/api/v1/projects/{pid}/costs", json=body).json()["data"]


def test_cost_edit_persists(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    cost = _add_cost(client, pid, amount_try="1000")
    r = client.put(f"/api/v1/projects/{pid}/costs/{cost['id']}", json={"amount_try": "2500"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["amount_try"] == "2500.00"


def test_pm_can_soft_delete_cost(client, seed):
    # CR-001-G widened delete to Director + Project Manager.
    pm = seed["a"]["users"][ROLE_PROJECT_MANAGER]
    client.login(pm)
    pid = seed["a"]["project"].id
    cost = _add_cost(client, pid)
    r = client.delete(f"/api/v1/projects/{pid}/costs/{cost['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"] == 0


def test_invoice_status_can_be_reverted(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    inv = client.post(
        f"/api/v1/projects/{pid}/invoices",
        json={"invoice_number": "REV-1", "invoice_date": "2025-02-01", "amount_try": "100000", "vat_rate": "0", "due_date": "2025-03-01"},
    ).json()["data"]
    # Mark paid.
    client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"payment_status": "paid", "amount_received_try": "100000", "date_received": "2025-03-10"})
    # Revert to unpaid.
    r = client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"payment_status": "unpaid", "amount_received_try": "0"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["payment_status"] == "unpaid"


def test_equipment_update(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    e = client.post(
        f"/api/v1/projects/{pid}/equipment",
        json={"equipment_name": "Vinç", "ownership_type": "rented", "deployment_start": "2025-03-01", "add_to_budget": False},
    ).json()["data"]
    r = client.put(f"/api/v1/projects/{pid}/equipment/{e['id']}", json={"equipment_name": "Mobil Vinç"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["equipment_name"] == "Mobil Vinç"


def test_template_requires_auth_but_works_when_logged_in(client, seed):
    # Unauthenticated -> 401 (the original bug was a missing auth header).
    assert client.get(f"/api/v1/projects/{seed['a']['project'].id}/costs/import/template").status_code == 401
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{seed['a']['project'].id}/costs/import/template")
    assert r.status_code == 200
