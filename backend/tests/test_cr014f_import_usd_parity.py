"""CR-014 fix — USD snapshot parity on the import paths.

Costs created via the Excel import (and the AI import) previously bypassed the
CR-014-B USD snapshot, leaving amount_usd NULL → Proje Özeti showed "$0.00 / kur
bulunamadı" for imported projects. These tests assert the import paths now snapshot
USD just like the manual create path.

No network: fx_rates are seeded and the conftest keeps live TCMB fetch off, so
rate_as_of resolves purely from the seeded cache (incl. walk-back).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate

API = "/api/v1"


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def test_excel_import_confirm_snapshots_usd(client, seed, db):
    # A single seeded rate; the second row's date walks back to it (one cache hit,
    # no per-row network — proves a bulk import across dates is cheap).
    pid = _login(client, seed)
    _seed_rate(db, "2025-05-01", "32.0000")
    rows = [
        {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "64000", "vat_rate": "20"},
        {"entry_date": "2025-05-02", "cost_category": "labour_direct", "amount_try": "32000", "vat_rate": "20"},
    ]
    r = client.post(f"{API}/projects/{pid}/costs/import/confirm", json={"rows": rows})
    assert r.status_code == 200, r.text
    costs = db.execute(
        select(CostEntry).where(CostEntry.project_id == pid).order_by(CostEntry.entry_date)
    ).scalars().all()
    assert len(costs) == 2
    # No imported row is left amount_usd NULL when a rate is available.
    for c in costs:
        assert c.fx_rate_usd == Decimal("32.0000")
        assert c.amount_usd is not None
    assert costs[0].amount_usd == Decimal("2000.00")  # 64000 / 32
    assert costs[1].amount_usd == Decimal("1000.00")  # 32000 / 32 (walk-back)


def test_excel_import_paid_row_snapshots_at_payment_date(client, seed, db):
    # Paid rows lock to the PAYMENT-date rate (§2.2), not the entry-date rate.
    pid = _login(client, seed)
    _seed_rate(db, "2025-05-01", "30.0000")  # entry-date rate
    _seed_rate(db, "2025-06-01", "40.0000")  # payment-date rate (the lock)
    rows = [{
        "entry_date": "2025-05-01", "cost_category": "other", "amount_try": "40000", "vat_rate": "20",
        "payment_status": "paid", "date_paid": "2025-06-01",
    }]
    r = client.post(f"{API}/projects/{pid}/costs/import/confirm", json={"rows": rows})
    assert r.status_code == 200, r.text
    c = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().one()
    assert c.fx_rate_usd == Decimal("40.0000")
    assert c.amount_usd == Decimal("1000.00")  # 40000 / 40


def test_excel_import_no_rate_leaves_usd_null_gracefully(client, seed, db):
    # Pre-history (no seeded rate at all) → USD left null, never blocks the import.
    pid = _login(client, seed)
    rows = [{"entry_date": "2025-05-01", "cost_category": "other", "amount_try": "1000", "vat_rate": "20"}]
    r = client.post(f"{API}/projects/{pid}/costs/import/confirm", json={"rows": rows})
    assert r.status_code == 200, r.text
    c = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().one()
    assert c.amount_usd is None and c.fx_rate_usd is None


def test_ai_import_confirm_snapshots_usd(client, seed, db):
    pid = _login(client, seed)
    _seed_rate(db, "2025-05-01", "25.0000")
    body = {"maliyet_girisleri": [
        {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "50000", "vat_rate": "20"},
    ]}
    r = client.post(f"{API}/projects/{pid}/ai-import/confirm", json=body)
    assert r.status_code == 200, r.text
    c = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().one()
    assert c.fx_rate_usd == Decimal("25.0000")
    assert c.amount_usd == Decimal("2000.00")  # 50000 / 25
