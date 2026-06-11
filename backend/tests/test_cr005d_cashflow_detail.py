"""CR-005-D: cash-flow month drawer — unpaid costs & uncollected invoices.

The drawer showed "Gider Tahminleri (0)" / "Beklenen Tahsilat (0)" because the old
client-side fetch requested per_page=500 (cap 100) and the 422 emptied both lists.
The new /cashflow/detail endpoint filters server-side by an explicit month range.
"""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _cost(client, pid, due_date, amount, category="material_concrete"):
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={
            "entry_date": "2026-05-01", "cost_category": category, "amount_try": amount,
            "vat_rate": "0", "payment_due_date": due_date,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _invoice(client, pid, due_date, amount, number):
    r = client.post(
        f"/api/v1/projects/{pid}/invoices",
        json={"invoice_number": number, "invoice_date": "2026-05-01", "amount_try": amount,
              "vat_rate": "0", "due_date": due_date},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_detail_returns_costs_and_invoices_due_in_month(client, seed):
    pid = _login(client, seed)
    _cost(client, pid, "2026-06-15", "100000")
    _cost(client, pid, "2026-06-28", "50000")
    _invoice(client, pid, "2026-06-20", "200000", "HAK-J1")

    data = client.get(f"/api/v1/projects/{pid}/cashflow/detail", params={"month": "2026-06"}).json()["data"]
    assert len(data["costs"]) == 2
    assert len(data["invoices"]) == 1
    assert data["total_out_try"] == "150000.00"
    assert data["total_in_try"] == "200000.00"
    assert data["net_try"] == "50000.00"


def test_detail_excludes_other_months(client, seed):
    pid = _login(client, seed)
    _cost(client, pid, "2026-05-15", "100000")   # May — excluded
    _cost(client, pid, "2026-07-01", "100000")   # July — excluded
    _invoice(client, pid, "2026-07-10", "100000", "HAK-J2")  # July — excluded

    data = client.get(f"/api/v1/projects/{pid}/cashflow/detail", params={"month": "2026-06"}).json()["data"]
    assert data["costs"] == []
    assert data["invoices"] == []
    assert data["total_out_try"] == "0.00"
    assert data["net_try"] == "0.00"


def test_detail_excludes_fully_paid(client, seed):
    """A fully collected invoice is not an 'expected collection'."""
    pid = _login(client, seed)
    inv = _invoice(client, pid, "2026-06-10", "100000", "HAK-J3")
    client.put(f"/api/v1/projects/{pid}/invoices/{inv['id']}", json={"amount_received_try": "100000", "date_received": "2026-06-11"})

    data = client.get(f"/api/v1/projects/{pid}/cashflow/detail", params={"month": "2026-06"}).json()["data"]
    assert data["invoices"] == []


def test_detail_rejects_bad_month(client, seed):
    pid = _login(client, seed)
    assert client.get(f"/api/v1/projects/{pid}/cashflow/detail", params={"month": "haziran"}).status_code == 422
