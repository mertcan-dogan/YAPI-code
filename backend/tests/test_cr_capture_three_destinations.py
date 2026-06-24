"""Smart document-capture confirm: three destinations (cost / equipment / income).

Covers ``POST /api/v1/document-capture/confirm`` (smart_capture_confirm and the
helpers _confirm_cost / _confirm_equipment / _confirm_income). The AI only
*suggests* the destination; a human confirms here before any write. Each branch
reuses an existing creation path, so the financial invariants must match those
paths exactly:

  - equipment + add_to_budget -> ONE committed CostEntry, amount == equipment_cost,
    no double count (the EquipmentLog itself is not a cost row).
  - income -> ClientInvoice net_due == total_with_vat - retention, same as
    POST /projects/{id}/invoices.

Tenant scoping (get_company_project) and the invoice-creator role gate must hold.
"""
from decimal import Decimal

from app.calculations.equipment import equipment_cost
from app.constants import (
    ROLE_DIRECTOR,
    ROLE_FINANCE,
    ROLE_PROJECT_MANAGER,
    ROLE_SITE_MANAGER,
)

D = Decimal

CONFIRM_URL = "/api/v1/document-capture/confirm"


def _project_a(seed):
    return seed["a"]["project"]


# --------------------------------------------------------------------------- #
# 1. Regression: omitted / "cost" destination still creates a CostEntry
# --------------------------------------------------------------------------- #
def test_destination_omitted_creates_cost_entry(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "document_path": f"{pid}/abc.png",
        "entry_date": "2025-05-01",
        "cost_category": "material_concrete",
        "supplier_name": "Beton A.Ş.",
        "invoice_number": "F-2025-1",
        "amount_try": "150000",
        "vat_rate": "20",
        "payment_status": "unpaid",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["destination"] == "cost"
    assert data["cost_category"] == "material_concrete"

    costs = client.get(f"/api/v1/projects/{pid}/costs").json()
    assert costs["meta"]["total"] == 1
    row = costs["data"][0]
    assert row["entry_type"] == "actual"  # legacy capture is an actual cost
    assert row["document_url"] == f"documents/{pid}/abc.png"
    # VAT math matches calc_fields.
    assert D(str(row["vat_amount_try"])) == D("30000.00")
    assert D(str(row["total_with_vat_try"])) == D("180000.00")


def test_destination_cost_explicit_creates_cost_entry(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "cost",
        "entry_date": "2025-05-01",
        "cost_category": "material_steel",
        "amount_try": "1000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["destination"] == "cost"
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()
    assert costs["meta"]["total"] == 1


# --------------------------------------------------------------------------- #
# 2. destination="equipment" + add_to_budget=true -> EquipmentLog + committed cost
# --------------------------------------------------------------------------- #
def test_equipment_with_budget_creates_log_and_committed_cost(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "equipment",
        "equipment_name": "Ekskavatör",
        "ownership_type": "rented",
        "supplier_name": "Kiralık Makine Ltd.",
        "rate_try": "5000",
        "rate_unit": "day",
        "deployment_start": "2025-05-01",
        "deployment_end": "2025-05-10",  # inclusive 10 days
        "fuel_maintenance_try": "2000",
        "add_to_budget": True,
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["destination"] == "equipment"
    assert data["equipment_name"] == "Ekskavatör"

    # EquipmentLog row exists, scoped to the project.
    eq = client.get(f"/api/v1/projects/{pid}/equipment").json()
    assert eq["meta"]["total"] == 1

    # Exactly one committed CostEntry, and its amount equals equipment_cost
    # (no double count: the EquipmentLog itself is not a cost row).
    expected = equipment_cost("rented", D("5000"), "day", _d("2025-05-01"), _d("2025-05-10"), D("2000"))
    assert expected == D("52000")  # 5000*10 + 2000
    committed = client.get(f"/api/v1/projects/{pid}/costs?entry_type=committed").json()
    assert committed["meta"]["total"] == 1
    crow = committed["data"][0]
    assert crow["entry_type"] == "committed"
    assert crow["cost_category"] == "equipment_rented"
    assert D(str(crow["amount_try"])) == expected
    assert D(str(crow["vat_amount_try"])) == D("10400.00")  # 52000 * 20%
    assert D(str(crow["total_with_vat_try"])) == D("62400.00")

    # No actual cost rows were created (no double count).
    actuals = client.get(f"/api/v1/projects/{pid}/costs?entry_type=actual").json()
    assert actuals["meta"]["total"] == 0


def test_equipment_committed_cost_scoped_to_company_and_project(client, seed):
    """The committed cost belongs to company A's project, not company B."""
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid_a = _project_a(seed).id
    body = {
        "project_id": str(pid_a),
        "destination": "equipment",
        "equipment_name": "Vinç",
        "ownership_type": "rented",
        "rate_try": "1000",
        "rate_unit": "day",
        "deployment_start": "2025-05-01",
        "deployment_end": "2025-05-02",
        "add_to_budget": True,
    }
    assert client.post(CONFIRM_URL, json=body).status_code == 200

    # Company B sees nothing on its own project.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    pid_b = seed["b"]["project"].id
    eq_b = client.get(f"/api/v1/projects/{pid_b}/equipment").json()
    assert eq_b["meta"]["total"] == 0
    costs_b = client.get(f"/api/v1/projects/{pid_b}/costs").json()
    assert costs_b["meta"]["total"] == 0


# --------------------------------------------------------------------------- #
# 3. destination="equipment" + add_to_budget=false -> log only, no cost
# --------------------------------------------------------------------------- #
def test_equipment_without_budget_creates_no_cost(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "equipment",
        "equipment_name": "Jeneratör",
        "ownership_type": "rented",
        "rate_try": "3000",
        "rate_unit": "day",
        "deployment_start": "2025-05-01",
        "deployment_end": "2025-05-05",
        "add_to_budget": False,
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    eq = client.get(f"/api/v1/projects/{pid}/equipment").json()
    assert eq["meta"]["total"] == 1
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()
    assert costs["meta"]["total"] == 0


# --------------------------------------------------------------------------- #
# 4. destination="income" as an allowed role -> ClientInvoice with correct math
# --------------------------------------------------------------------------- #
def test_income_director_creates_invoice_with_correct_net_due(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "income",
        "document_path": f"{pid}/hak.png",
        "invoice_number": "HK-2025-01",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "hakkedis_period": "2025-05",
        "description": "1. Hakediş",
        "amount_try": "100000",
        "vat_rate": "20",
        "retention_amount_try": "5000",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["destination"] == "income"
    assert data["invoice_number"] == "HK-2025-01"

    invs = client.get(f"/api/v1/projects/{pid}/invoices").json()
    assert invs["meta"]["total"] == 1
    inv = invs["data"][0]
    # total_with_vat = 120000; net_due = 120000 - 5000 retention = 115000.
    assert D(str(inv["vat_amount_try"])) == D("20000.00")
    assert D(str(inv["total_with_vat_try"])) == D("120000.00")
    assert D(str(inv["net_due_try"])) == D("115000.00")
    assert inv["payment_status"] == "unpaid"
    assert inv["document_url"] == f"documents/{pid}/hak.png"

    # No cost rows leaked from the income branch.
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()
    assert costs["meta"]["total"] == 0


def test_income_finance_role_allowed(client, seed):
    client.login(seed["a"]["users"][ROLE_FINANCE])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "income",
        "invoice_number": "HK-FIN-1",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "amount_try": "10000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["destination"] == "income"


def test_income_pm_role_allowed(client, seed):
    pm = seed["a"]["users"][ROLE_PROJECT_MANAGER]
    client.login(pm)
    pid = _project_a(seed).id  # PM owns project A (project_manager_id == pm.id)
    body = {
        "project_id": str(pid),
        "destination": "income",
        "invoice_number": "HK-PM-1",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "amount_try": "10000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# 5. destination="income" as a forbidden role -> 403, no invoice
# --------------------------------------------------------------------------- #
def test_income_site_manager_forbidden(client, seed):
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "income",
        "invoice_number": "HK-SM-1",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "amount_try": "10000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 403, r.text

    # No invoice was created (check as a privileged role).
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    invs = client.get(f"/api/v1/projects/{pid}/invoices").json()
    assert invs["meta"]["total"] == 0


# --------------------------------------------------------------------------- #
# 6. destination="income" duplicate (project_id, invoice_number) -> 422, no 2nd row
# --------------------------------------------------------------------------- #
def test_income_duplicate_invoice_number_rejected(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "income",
        "invoice_number": "DUP-1",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "amount_try": "10000",
        "vat_rate": "20",
    }
    assert client.post(CONFIRM_URL, json=body).status_code == 200

    r2 = client.post(CONFIRM_URL, json=body)
    assert r2.status_code == 422, r2.text
    assert r2.json()["error"]["message"] == "Bu fatura numarası zaten mevcut"

    invs = client.get(f"/api/v1/projects/{pid}/invoices").json()
    assert invs["meta"]["total"] == 1  # no second row


# --------------------------------------------------------------------------- #
# 7. destination="invalid" -> 422
# --------------------------------------------------------------------------- #
def test_invalid_destination_rejected(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _project_a(seed).id
    body = {
        "project_id": str(pid),
        "destination": "banana",
        "entry_date": "2025-05-01",
        "cost_category": "material_steel",
        "amount_try": "1000",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 422, r.text
    # Nothing was written anywhere.
    assert client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/projects/{pid}/equipment").json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/projects/{pid}/invoices").json()["meta"]["total"] == 0


# --------------------------------------------------------------------------- #
# 8. Tenant isolation: confirm against another company's project -> 404, no write
# --------------------------------------------------------------------------- #
def test_cross_company_project_not_found_cost(client, seed):
    # Director of company A targets company B's project.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid_b = seed["b"]["project"].id
    body = {
        "project_id": str(pid_b),
        "destination": "cost",
        "entry_date": "2025-05-01",
        "cost_category": "material_steel",
        "amount_try": "1000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 404, r.text

    # Confirm no cross-company cost write (check as company B's director).
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"/api/v1/projects/{pid_b}/costs").json()["meta"]["total"] == 0


def test_cross_company_project_not_found_equipment(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid_b = seed["b"]["project"].id
    body = {
        "project_id": str(pid_b),
        "destination": "equipment",
        "equipment_name": "Vinç",
        "ownership_type": "rented",
        "rate_try": "1000",
        "rate_unit": "day",
        "deployment_start": "2025-05-01",
        "deployment_end": "2025-05-02",
        "add_to_budget": True,
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 404, r.text
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"/api/v1/projects/{pid_b}/equipment").json()["meta"]["total"] == 0
    assert client.get(f"/api/v1/projects/{pid_b}/costs").json()["meta"]["total"] == 0


def test_cross_company_project_not_found_income(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid_b = seed["b"]["project"].id
    body = {
        "project_id": str(pid_b),
        "destination": "income",
        "invoice_number": "HK-X",
        "invoice_date": "2025-05-01",
        "due_date": "2025-06-01",
        "amount_try": "10000",
        "vat_rate": "20",
    }
    r = client.post(CONFIRM_URL, json=body)
    assert r.status_code == 404, r.text
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"/api/v1/projects/{pid_b}/invoices").json()["meta"]["total"] == 0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _d(s):
    from datetime import date

    return date.fromisoformat(s)
