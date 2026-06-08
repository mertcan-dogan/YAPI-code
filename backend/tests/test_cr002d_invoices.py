"""CR-002-D: partial payment auto-status + document_url."""
from app.constants import ROLE_DIRECTOR


def _invoice(client, pid, **over):
    body = {"invoice_number": "HAK-D1", "invoice_date": "2025-02-01", "amount_try": "100000",
            "vat_rate": "0", "due_date": "2025-03-01"}
    body.update(over)
    return client.post(f"/api/v1/projects/{pid}/invoices", json=body).json()["data"]


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_partial_payment_sets_partial_status(client, seed):
    pid = _login(client, seed)
    inv = _invoice(client, pid)  # net_due = 100000 (vat 0, no retention)
    r = client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"amount_received_try": "40000", "date_received": "2025-03-05"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["payment_status"] == "partial"
    assert r.json()["data"]["outstanding_try"] == "60000.00"


def test_full_payment_sets_paid_status(client, seed):
    pid = _login(client, seed)
    inv = _invoice(client, pid, invoice_number="HAK-D2")
    r = client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"amount_received_try": "100000", "date_received": "2025-03-05"})
    assert r.json()["data"]["payment_status"] == "paid"


def test_zero_received_is_unpaid(client, seed):
    pid = _login(client, seed)
    inv = _invoice(client, pid, invoice_number="HAK-D3")
    client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"amount_received_try": "50000"})
    r = client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"amount_received_try": "0"})
    assert r.json()["data"]["payment_status"] == "unpaid"


def test_invoice_document_url_persists(client, seed):
    pid = _login(client, seed)
    inv = _invoice(client, pid, invoice_number="HAK-D4", document_url="https://example.com/a.pdf")
    assert inv["document_url"] == "https://example.com/a.pdf"
