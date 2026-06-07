"""CR-001-H: audit log API (filters, access control, export)."""
from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER


def _make_change(client, seed):
    """Create + update a cost so audit rows exist."""
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    cost = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2025-03-01", "cost_category": "other", "amount_try": "1000"},
    ).json()["data"]
    client.put(f"/api/v1/projects/{pid}/costs/{cost['id']}", json={"amount_try": "1500"})
    return pid


def test_audit_log_lists_changes_with_labels(client, seed):
    _make_change(client, seed)
    r = client.get("/api/v1/audit-log")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    actions = {row["action"] for row in rows}
    assert "INSERT" in actions and "UPDATE" in actions
    upd = next(row for row in rows if row["action"] == "UPDATE")
    assert upd["action_label"] == "Güncellendi"
    assert upd["table_label"] == "Maliyet Girişi"
    assert upd["user_name"]  # resolved name, not blank
    # old/new values present for the diff view.
    assert upd["old_values"]["amount_try"] in ("1000", "1000.00")
    assert upd["new_values"]["amount_try"] in ("1500", "1500.00")


def test_audit_log_action_filter(client, seed):
    _make_change(client, seed)
    rows = client.get("/api/v1/audit-log", params={"action": "UPDATE"}).json()["data"]
    assert rows and all(r["action"] == "UPDATE" for r in rows)


def test_audit_log_director_only(client, seed):
    # Non-director (PM) must be forbidden.
    client.login(seed["a"]["users"][ROLE_PROJECT_MANAGER])
    assert client.get("/api/v1/audit-log").status_code == 403


def test_audit_log_export_xlsx(client, seed):
    _make_change(client, seed)
    r = client.get("/api/v1/audit-log/export")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
