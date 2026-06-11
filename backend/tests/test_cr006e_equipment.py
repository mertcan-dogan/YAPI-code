"""CR-006-E: ekipman kayıt sayfası — uçtan uca doğrulama.

Sayfanın dayandığı backend sözleşmesini kilitler: liste meta'sında toplam maliyet
ve bütçe yüzdesi, gün/ay süre + maliyet hesabı, ve checkbox ile otomatik cost_entry.
"""
from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry


def _add_equipment(client, project_id, **kw):
    body = {
        "equipment_name": "Vinç", "ownership_type": "rented", "supplier_name": "Kiralama A.Ş.",
        "rate_try": "1000", "rate_unit": "day",
        "deployment_start": "2026-01-01", "deployment_end": "2026-01-20",
        "fuel_maintenance_try": "500", "add_to_budget": True,
    }
    body.update(kw)
    return client.post(f"/api/v1/projects/{project_id}/equipment", json=body)


def test_page_lists_with_totals(client, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    assert _add_equipment(client, a["project"].id).status_code == 200

    r = client.get(f"/api/v1/projects/{a['project'].id}/equipment")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["data"]
    assert len(rows) == 1
    # Gün hesabı: 01.01 -> 20.01 = 20 gün; 1000×20 + 500 yakıt = 20.500.
    assert rows[0]["duration_days"] == 20
    assert rows[0]["total_cost_try"] == "20500.00"
    # Sayfa üstü chip verileri meta'da.
    assert body["meta"]["total_cost_try"] == "20500.00"
    assert "pct_of_budget" in body["meta"]


def test_monthly_rate_cost(client, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    # 3 tam ay (01.01 -> 01.04), aylık 10.000 -> 30.000 + 0 yakıt.
    r = _add_equipment(
        client, a["project"].id, equipment_name="Jeneratör", rate_try="10000",
        rate_unit="month", deployment_start="2026-01-01", deployment_end="2026-04-01",
        fuel_maintenance_try="0",
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total_cost_try"] == "30000.00"


def test_checkbox_creates_cost_entry(client, db, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    assert _add_equipment(client, a["project"].id, add_to_budget=True).status_code == 200

    costs = db.execute(
        select(CostEntry).where(CostEntry.project_id == a["project"].id)
    ).scalars().all()
    assert len(costs) == 1
    assert costs[0].cost_category == "equipment_rented"


def test_unchecked_creates_no_cost_entry(client, db, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    assert _add_equipment(client, a["project"].id, add_to_budget=False).status_code == 200

    costs = db.execute(
        select(CostEntry).where(CostEntry.project_id == a["project"].id)
    ).scalars().all()
    assert costs == []
