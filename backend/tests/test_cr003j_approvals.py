"""CR-003-J: approval workflow for large cost entries."""
from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER


def _login_dir(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _big_cost(client, pid, amount="600000"):
    return client.post(f"/api/v1/projects/{pid}/costs", json={"entry_date": "2026-03-01", "cost_category": "other", "amount_try": amount, "vat_rate": "0"}).json()["data"]


def test_large_cost_goes_pending_and_excluded_from_dashboard(client, seed):
    pid = _login_dir(client, seed)
    cost = _big_cost(client, pid, "600000")  # > 500k default threshold
    assert cost["pending_approval"] is True
    # Excluded from dashboard financials.
    fin = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["financials"]
    assert fin["total_actual_try"] == "0.00"


def test_small_cost_not_pending(client, seed):
    pid = _login_dir(client, seed)
    cost = _big_cost(client, pid, "100000")
    assert cost["pending_approval"] is False


def test_approval_activates_cost(client, seed):
    pid = _login_dir(client, seed)
    cost = _big_cost(client, pid, "600000")
    pending = client.get("/api/v1/approvals").json()
    assert pending["meta"]["total"] == 1
    r = client.put(f"/api/v1/approvals/cost/{cost['id']}/approve", json={})
    assert r.status_code == 200
    # Now counted in the dashboard.
    fin = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["financials"]
    assert fin["total_actual_try"] == "600000.00"
    assert client.get("/api/v1/approvals").json()["meta"]["total"] == 0


def test_reject_requires_reason_and_removes(client, seed):
    pid = _login_dir(client, seed)
    cost = _big_cost(client, pid, "600000")
    # Empty reason rejected.
    assert client.put(f"/api/v1/approvals/cost/{cost['id']}/reject", json={"reason": ""}).status_code == 422
    r = client.put(f"/api/v1/approvals/cost/{cost['id']}/reject", json={"reason": "Bütçe dışı"})
    assert r.status_code == 200
    assert client.get("/api/v1/approvals").json()["meta"]["total"] == 0


def test_approvals_director_only(client, seed):
    client.login(seed["a"]["users"][ROLE_PROJECT_MANAGER])
    assert client.get("/api/v1/approvals").status_code == 403


def test_threshold_configurable(client, seed):
    pid = _login_dir(client, seed)
    # Lower the threshold to 50k so a 100k entry becomes pending.
    client.put("/api/v1/settings/company", json={"cost_approval_threshold_try": 50000})
    cost = _big_cost(client, pid, "100000")
    assert cost["pending_approval"] is True
