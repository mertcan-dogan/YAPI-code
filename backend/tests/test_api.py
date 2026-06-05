"""API endpoint tests (Section 12.2). SQLite-backed via portable types."""
from app.constants import ROLE_DIRECTOR, ROLE_FINANCE, ROLE_PROJECT_MANAGER
from app.models.audit_log import AuditLog


def _project_payload(**over):
    base = {
        "name": "Yeni Proje",
        "project_code": "PRJ-NEW",
        "project_type": "road",
        "client_name": "İşveren A.Ş.",
        "contract_value_try": "2000000",
        "original_budget_try": "1600000",
        "start_date": "2025-01-01",
        "planned_end_date": "2025-12-31",
    }
    base.update(over)
    return base


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_unauthenticated_returns_401(client, seed):
    r = client.get("/api/v1/projects")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHENTICATED"


def test_director_can_create_and_list_project(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_project_payload())
    assert r.status_code == 200, r.text
    assert r.json()["success"] is True

    r2 = client.get("/api/v1/projects")
    assert r2.status_code == 200
    names = [p["name"] for p in r2.json()["data"]]
    assert "Yeni Proje" in names


def test_pm_cannot_create_project_403(client, seed):
    client.login(seed["a"]["users"][ROLE_PROJECT_MANAGER])
    r = client.post("/api/v1/projects", json=_project_payload())
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_cross_company_access_returns_404(client, seed):
    # User from company B tries to read company A's project.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    a_project_id = seed["a"]["project"].id
    r = client.get(f"/api/v1/projects/{a_project_id}")
    assert r.status_code == 404


def test_contract_value_validation_422_turkish(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_project_payload(contract_value_try="0"))
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "0'dan büyük" in body["error"]["message"]


def test_cost_crud_and_soft_delete(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id

    # Create
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={
            "entry_date": "2025-03-01",
            "cost_category": "material_concrete",
            "amount_try": "100000",
            "vat_rate": "20",
            "supplier_name": "Akçansa",
        },
    )
    assert r.status_code == 200, r.text
    cost = r.json()["data"]
    # VAT computed: 100000 * 20% = 20000; total 120000
    assert cost["vat_amount_try"] == "20000.00"
    assert cost["total_with_vat_try"] == "120000.00"
    cost_id = cost["id"]

    # List shows it
    r = client.get(f"/api/v1/projects/{pid}/costs")
    assert r.json()["meta"]["total"] == 1

    # Soft delete (director)
    r = client.delete(f"/api/v1/projects/{pid}/costs/{cost_id}")
    assert r.status_code == 200

    # No longer listed
    r = client.get(f"/api/v1/projects/{pid}/costs")
    assert r.json()["meta"]["total"] == 0


def test_audit_log_created_on_cost_update(client, seed, db):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2025-03-01", "cost_category": "other", "amount_try": "5000"},
    )
    cost_id = r.json()["data"]["id"]
    client.put(
        f"/api/v1/projects/{pid}/costs/{cost_id}",
        json={"amount_try": "7500"},
    )
    rows = db.query(AuditLog).filter(AuditLog.table_name == "cost_entries").all()
    actions = {row.action for row in rows}
    assert "INSERT" in actions
    assert "UPDATE" in actions


def test_invoice_number_unique_per_project(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    payload = {
        "invoice_number": "HAK-001",
        "invoice_date": "2025-02-01",
        "amount_try": "500000",
        "vat_rate": "20",
        "due_date": "2025-03-01",
    }
    r1 = client.post(f"/api/v1/projects/{pid}/invoices", json=payload)
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/api/v1/projects/{pid}/invoices", json=payload)
    assert r2.status_code == 422
    assert r2.json()["error"]["message"] == "Bu fatura numarası zaten mevcut"


def test_invoice_due_before_invoice_date_rejected(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    r = client.post(
        f"/api/v1/projects/{pid}/invoices",
        json={
            "invoice_number": "HAK-002",
            "invoice_date": "2025-05-01",
            "amount_try": "100000",
            "due_date": "2025-04-01",  # before invoice date
        },
    )
    assert r.status_code == 422


def test_invoice_net_due_and_outstanding_computed(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    r = client.post(
        f"/api/v1/projects/{pid}/invoices",
        json={
            "invoice_number": "HAK-010",
            "invoice_date": "2025-02-01",
            "amount_try": "1000000",
            "vat_rate": "20",
            "retention_amount_try": "100000",
            "due_date": "2025-03-01",
        },
    )
    inv = r.json()["data"]
    # total = 1,200,000; net due = 1,200,000 - 100,000 = 1,100,000
    assert inv["total_with_vat_try"] == "1200000.00"
    assert inv["net_due_try"] == "1100000.00"
    # outstanding (computed column) = net_due - received(0)
    assert inv["outstanding_try"] == "1100000.00"


def test_project_dashboard_returns_financials(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    client.login(director)
    pid = seed["a"]["project"].id
    r = client.get(f"/api/v1/projects/{pid}/dashboard")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "financials" in data
    assert data["financials"]["rag_status"] in ("red", "amber", "green")
