"""CR-005-E: audit log surfaces only the changed fields, not the full JSON dump."""
from app.api.audit import compute_changed_fields
from app.constants import ROLE_DIRECTOR


def test_compute_changed_fields_only_diff():
    old = {"amount_try": "15000000", "payment_due_date": "2026-05-01", "supplier_name": "Akçansa"}
    new = {"amount_try": "18000000", "payment_due_date": "2026-06-01", "supplier_name": "Akçansa"}
    changed = compute_changed_fields(old, new)
    fields = {c["field"] for c in changed}
    assert fields == {"amount_try", "payment_due_date"}  # supplier unchanged → excluded
    amt = next(c for c in changed if c["field"] == "amount_try")
    assert amt["old"] == "15000000" and amt["new"] == "18000000"


def test_compute_changed_fields_ignores_housekeeping():
    old = {"amount_try": "100", "updated_at": "t1", "id": "x"}
    new = {"amount_try": "100", "updated_at": "t2", "id": "x"}
    assert compute_changed_fields(old, new) == []  # only updated_at differs → ignored


def test_compute_changed_fields_insert_delete_empty():
    assert compute_changed_fields(None, {"a": 1}) == []
    assert compute_changed_fields({"a": 1}, None) == []


def test_audit_endpoint_returns_changed_fields(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id

    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2026-03-01", "cost_category": "other", "amount_try": "5000"},
    )
    cid = r.json()["data"]["id"]
    client.put(f"/api/v1/projects/{pid}/costs/{cid}", json={"amount_try": "8000"})

    rows = client.get("/api/v1/audit-log", params={"table_name": "cost_entries", "action": "UPDATE"}).json()["data"]
    assert rows, "beklenen UPDATE audit kaydı yok"
    row = rows[0]
    assert "changed_fields" in row
    changed_keys = {c["field"] for c in row["changed_fields"]}
    assert "amount_try" in changed_keys
    # Each changed field carries old + new, never the whole record.
    for c in row["changed_fields"]:
        assert set(c.keys()) == {"field", "old", "new"}
