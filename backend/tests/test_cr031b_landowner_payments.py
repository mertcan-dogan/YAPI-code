"""CR-031-B: landowner payment ledger + FX-at-date + SQL rollup.

No network: fx_rates are seeded; conftest keeps live TCMB fetch off.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.fx_rate import FxRate
from app.models.landowner_payment import LandownerPayment


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _login_dir(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])
    return seed[label]["project"].id


# --------------------------------------------------------------------------- #
# CRUD + FX-at-date
# --------------------------------------------------------------------------- #
def test_create_snapshots_usd_at_payment_date(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-04-01", "40.0000")
    r = client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payer_name": "Arsa Sahipleri Toplu", "payment_date": "2025-04-01",
        "amount_try": "8000000", "committed_total_try": "20000000",
    })
    assert r.status_code == 200, r.text
    p = db.execute(select(LandownerPayment).where(LandownerPayment.project_id == pid)).scalars().one()
    assert p.fx_rate_usd == Decimal("40.0000")
    assert p.amount_usd == Decimal("200000.00")  # 8,000,000 / 40


def test_create_without_rate_leaves_usd_null(client, seed, db):
    pid = _login_dir(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "5000000",
    })
    assert r.status_code == 200, r.text  # not blocked
    p = db.execute(select(LandownerPayment).where(LandownerPayment.project_id == pid)).scalars().one()
    assert p.amount_usd is None and p.fx_rate_usd is None


def test_update_reprices_usd(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-04-01", "40.0000")
    _seed_rate(db, "2025-07-01", "50.0000")
    pmid = client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "8000000",
    }).json()["data"]["id"]
    r = client.put(f"/api/v1/projects/{pid}/landowner-payments/{pmid}", json={"payment_date": "2025-07-01"})
    assert r.status_code == 200, r.text
    db.expire_all()
    p = db.get(LandownerPayment, pmid)
    assert p.fx_rate_usd == Decimal("50.0000")
    assert p.amount_usd == Decimal("160000.00")  # 8,000,000 / 50


def test_delete_is_soft(client, seed, db):
    pid = _login_dir(client, seed)
    pmid = client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "1000000",
    }).json()["data"]["id"]
    r = client.delete(f"/api/v1/projects/{pid}/landowner-payments/{pmid}")
    assert r.status_code == 200, r.text
    assert db.get(LandownerPayment, pmid).is_deleted is True
    led = client.get(f"/api/v1/projects/{pid}/landowner-payments").json()["data"]
    assert led["payments"] == []
    assert led["rollup"]["count"] == 0


# --------------------------------------------------------------------------- #
# SQL rollup: Σ TRY/USD, count, remaining-vs-committed (header max)
# --------------------------------------------------------------------------- #
def test_rollup_sums_and_remaining(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-04-01", "40.0000")
    # committed header repeats across rows; rollup takes the max (single value).
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "8000000", "committed_total_try": "20000000",
    })
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "5000000", "committed_total_try": "20000000",
    })
    rollup = client.get(f"/api/v1/projects/{pid}/landowner-payments").json()["data"]["rollup"]
    assert rollup["count"] == 2
    assert rollup["total_try"] == "13000000.00"
    assert rollup["total_usd"] == "325000.00"           # (8M+5M)/40
    assert rollup["committed_total_try"] == "20000000.00"
    assert rollup["remaining_try"] == "7000000.00"       # 20M - 13M
    assert rollup["pct_paid"] == "65.00"                 # 13M / 20M


def test_rollup_no_commitment_null_remaining(client, seed, db):
    pid = _login_dir(client, seed)
    client.post(f"/api/v1/projects/{pid}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "3000000",
    })
    rollup = client.get(f"/api/v1/projects/{pid}/landowner-payments").json()["data"]["rollup"]
    assert rollup["committed_total_try"] is None
    assert rollup["remaining_try"] is None and rollup["pct_paid"] is None
    assert rollup["total_try"] == "3000000.00"


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
def test_company_b_cannot_read_company_a(client, seed, db):
    pid_a = _login_dir(client, seed, "a")
    client.post(f"/api/v1/projects/{pid_a}/landowner-payments", json={
        "payment_date": "2025-04-01", "amount_try": "1000000",
    })
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{pid_a}/landowner-payments")
    assert r.status_code == 404
