"""End-to-end scenarios (Section 12.3)."""
from app.constants import ROLE_DIRECTOR


def _login_director(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_costs_flow_into_budget_and_dashboard(client, seed):
    """Create project (seeded) → enter 3 cost entries → verify budget vs actual
    table and dashboard KPIs reflect them."""
    pid = _login_director(client, seed)
    entries = [
        ("material_concrete", "100000"),
        ("material_steel", "150000"),
        ("labour_direct", "50000"),
    ]
    for cat, amt in entries:
        r = client.post(
            f"/api/v1/projects/{pid}/costs",
            json={"entry_date": "2025-03-01", "cost_category": cat, "amount_try": amt, "vat_rate": "20"},
        )
        assert r.status_code == 200, r.text

    # Budget table: concrete row shows 100,000 invoiced (actual).
    budget = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]
    concrete = next(c for c in budget["categories"] if c["cost_category"] == "material_concrete")
    assert concrete["invoiced_try"] == "100000.00"

    # Dashboard: total actual ex-VAT = 300,000; margin = (1,000,000 - 300,000)/1,000,000 = 70%.
    fin = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["financials"]
    assert fin["total_actual_try"] == "300000.00"
    assert fin["margin_pct"] == "70.00"


def test_invoice_collection_updates_cash_position(client, seed):
    """Enter client invoice → mark received → verify cash flow / net cash updates."""
    pid = _login_director(client, seed)

    # A paid cost so there is an outflow.
    client.post(
        f"/api/v1/projects/{pid}/costs",
        json={
            "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "100000",
            "vat_rate": "0", "payment_status": "paid", "date_paid": "2025-03-05",
            "amount_paid_try": "100000",
        },
    )

    inv = client.post(
        f"/api/v1/projects/{pid}/invoices",
        json={"invoice_number": "HAK-A1", "invoice_date": "2025-03-01", "amount_try": "500000",
              "vat_rate": "0", "due_date": "2025-04-01"},
    ).json()["data"]

    # Before collection: net cash = collected(0) - paid(100,000) = -100,000.
    fin = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["financials"]
    assert fin["net_cash_position_try"] == "-100000.00"

    # Mark invoice received in full.
    client.put(
        f"/api/v1/projects/{pid}/invoices/{inv['id']}",
        json={"payment_status": "paid", "date_received": "2025-03-20", "amount_received_try": "500000"},
    )

    fin2 = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["financials"]
    # net cash = collected(500,000) - paid(100,000) = 400,000.
    assert fin2["net_cash_position_try"] == "400000.00"
    assert fin2["total_collected_try"] == "500000.00"


def test_overdue_cost_appears_in_reminders(client, seed):
    """Enter overdue cost entry → it shows in cross-project reminders."""
    pid = _login_director(client, seed)
    client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2024-01-01", "cost_category": "other", "amount_try": "25000",
              "vat_rate": "20", "supplier_name": "Tedarikçi X", "payment_due_date": "2024-02-01"},
    )
    reminders = client.get("/api/v1/reminders").json()["data"]
    party_names = [r["party"] for r in reminders]
    assert "Tedarikçi X" in party_names
    overdue = next(r for r in reminders if r["party"] == "Tedarikçi X")
    assert overdue["days_remaining"] < 0  # past due
