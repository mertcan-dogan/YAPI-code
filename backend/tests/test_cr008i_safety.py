"""CR-008-I — write-endpoint rate limiting (workspace + vendor) via
enforce_user_limit (§10.1). RLS lives in migrations 0022/0023 (not exercised on
SQLite); company isolation is covered by the CR-008-A/H app-level tests."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.vendor import Vendor
from app.services import vendor_backfill as bf

CHART = {
    "chart_type": "bar", "title": "t", "x_key": "k",
    "series": [{"key": "v", "label": "V", "type": "bar"}],
    "data": [{"k": "a", "v": 1}],
}


def test_workspace_write_rate_limited(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "workspace_write_rate_per_minute", 2)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    body = {"title": "x", "item_type": "chart", "payload": CHART}
    assert client.post("/api/v1/workspace/items", json=body).status_code == 200
    assert client.post("/api/v1/workspace/items", json=body).status_code == 200
    r = client.post("/api/v1/workspace/items", json=body)  # 3rd
    assert r.status_code == 429
    assert "Çok fazla istek" in r.json()["error"]["message"]


def test_workspace_reads_not_rate_limited(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "workspace_write_rate_per_minute", 1)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    for _ in range(5):
        assert client.get("/api/v1/workspace/items").status_code == 200  # GET never limited


def test_vendor_write_rate_limited(client, seed, db, monkeypatch):
    cid = seed["a"]["company"].id
    p, uid = seed["a"]["project"], seed["a"]["users"][ROLE_DIRECTOR].id
    db.add(CostEntry(project_id=p.id, company_id=cid, entry_date=date(2026, 1, 1),
                     cost_category="other", supplier_name="Akçansa", amount_try=Decimal("100"),
                     vat_amount_try=Decimal("0"), total_with_vat_try=Decimal("100"),
                     payment_status="unpaid", entry_type="actual", created_by=uid))
    db.commit()
    bf.backfill_company(db, cid)
    vendor = db.execute(select(Vendor).where(Vendor.company_id == cid)).scalars().first()

    monkeypatch.setattr(settings, "vendor_write_rate_per_minute", 1)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    assert client.post(f"/api/v1/vendors/{vendor.id}/aliases", json={"alias_name": "Alias Bir"}).status_code == 200
    r = client.post(f"/api/v1/vendors/{vendor.id}/aliases", json={"alias_name": "Alias İki"})  # 2nd
    assert r.status_code == 429


def test_config_defaults():
    assert settings.workspace_write_rate_per_minute == 120
    assert settings.vendor_write_rate_per_minute == 30
