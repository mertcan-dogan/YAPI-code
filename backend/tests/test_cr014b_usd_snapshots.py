"""CR-014-B: per-row USD snapshots + backfill.

No network: fx_rates are seeded and the global conftest fixture keeps live TCMB
fetch off, so rate_as_of resolves purely from the seeded cache (incl. walk-back).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate
from app.services import fx, fx_backfill


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def _login_dir(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


class _Cost:
    """Lightweight stand-in for the snapshot helpers (duck-typed)."""
    def __init__(self, amount_try, entry_date, payment_status="unpaid", date_paid=None):
        self.amount_try = amount_try
        self.entry_date = entry_date
        self.payment_status = payment_status
        self.date_paid = date_paid
        self.amount_usd = None
        self.fx_rate_usd = None


# --------------------------------------------------------------------------- #
# Exact math
# --------------------------------------------------------------------------- #
def test_exact_usd_math_to_the_cent(db):
    _seed_rate(db, "2025-03-01", "32.2345")
    o = _Cost(Decimal("32234.50"), date(2025, 3, 1))
    assert fx.snapshot_cost_usd(db, o) is True
    assert o.fx_rate_usd == Decimal("32.2345")
    assert o.amount_usd == Decimal("1000.00")  # 32234.50 / 32.2345 == 1000 exactly


def test_usd_math_rounds_half_up_to_cent(db):
    _seed_rate(db, "2025-03-01", "3.0000")
    o = _Cost(Decimal("1000.00"), date(2025, 3, 1))
    fx.snapshot_cost_usd(db, o)
    assert o.amount_usd == Decimal("333.33")  # 1000/3 = 333.333... -> 333.33


# --------------------------------------------------------------------------- #
# Snapshot on create (API)
# --------------------------------------------------------------------------- #
def test_cost_create_snapshots_provisional(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "32.0000")
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "64000", "vat_rate": "20",
    })
    assert r.status_code == 200, r.text
    cost = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().one()
    assert cost.fx_rate_usd == Decimal("32.0000")
    assert cost.amount_usd == Decimal("2000.00")  # 64000 / 32


def test_invoice_create_snapshots_provisional(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-02-01", "30.0000")
    r = client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-USD-1", "invoice_date": "2025-02-01",
        "amount_try": "90000", "vat_rate": "0", "due_date": "2025-03-01",
    })
    assert r.status_code == 200, r.text
    inv = db.execute(select(ClientInvoice).where(ClientInvoice.project_id == pid)).scalars().one()
    assert inv.fx_rate_usd == Decimal("30.0000")
    assert inv.amount_usd == Decimal("3000.00")  # 90000 / 30


# --------------------------------------------------------------------------- #
# Lock on payment (re-snapshot at the payment-date rate)
# --------------------------------------------------------------------------- #
def test_cost_locks_at_payment_date_rate(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-03-01", "32.0000")   # entry date (provisional)
    _seed_rate(db, "2025-05-01", "40.0000")   # payment date (lock)
    cid = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "64000", "vat_rate": "0",
    }).json()["data"]["id"]

    cost = db.execute(select(CostEntry).where(CostEntry.id == cid)).scalars().one()
    assert cost.fx_rate_usd == Decimal("32.0000") and cost.amount_usd == Decimal("2000.00")

    # Record payment -> re-snapshots at the 2025-05-01 rate.
    r = client.put(f"/api/v1/projects/{pid}/costs/{cid}", json={"date_paid": "2025-05-01"})
    assert r.status_code == 200, r.text
    db.expire_all()
    cost = db.execute(select(CostEntry).where(CostEntry.id == cid)).scalars().one()
    assert cost.payment_status == "paid"
    assert cost.fx_rate_usd == Decimal("40.0000")
    assert cost.amount_usd == Decimal("1600.00")  # 64000 / 40 (was 2000 at the entry-date rate)


def test_invoice_locks_at_receipt_date_rate(client, seed, db):
    pid = _login_dir(client, seed)
    _seed_rate(db, "2025-02-01", "30.0000")   # invoice date (provisional)
    _seed_rate(db, "2025-04-15", "40.0000")   # receipt date (lock)
    iid = client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-USD-2", "invoice_date": "2025-02-01",
        "amount_try": "120000", "vat_rate": "0", "due_date": "2025-03-01",
    }).json()["data"]["id"]

    inv = db.execute(select(ClientInvoice).where(ClientInvoice.id == iid)).scalars().one()
    assert inv.fx_rate_usd == Decimal("30.0000") and inv.amount_usd == Decimal("4000.00")

    r = client.put(f"/api/v1/projects/{pid}/invoices/{iid}", json={
        "date_received": "2025-04-15", "amount_received_try": "120000",
    })
    assert r.status_code == 200, r.text
    db.expire_all()
    inv = db.execute(select(ClientInvoice).where(ClientInvoice.id == iid)).scalars().one()
    assert inv.payment_status == "paid"
    assert inv.fx_rate_usd == Decimal("40.0000")
    assert inv.amount_usd == Decimal("3000.00")  # 120000 / 40 (was 4000 at the invoice-date rate)


# --------------------------------------------------------------------------- #
# Weekend walk-back applies to snapshots too (cache-only, no fetch)
# --------------------------------------------------------------------------- #
def test_snapshot_uses_walk_back_for_weekend_date(db):
    # Friday has a rate; the entry falls on the Sunday with no published rate.
    _seed_rate(db, "2025-03-07", "31.5000")  # Friday
    assert date(2025, 3, 9).weekday() == 6   # Sunday
    o = _Cost(Decimal("31500.00"), date(2025, 3, 9))
    fx.snapshot_cost_usd(db, o)
    assert o.fx_rate_usd == Decimal("31.5000")
    assert o.amount_usd == Decimal("1000.00")


# --------------------------------------------------------------------------- #
# Null-rate: never blocks the save
# --------------------------------------------------------------------------- #
def test_cost_create_without_rate_leaves_usd_null(client, seed, db):
    pid = _login_dir(client, seed)  # no fx_rates seeded at all
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "5000", "vat_rate": "20",
    })
    assert r.status_code == 200, r.text  # save NOT blocked
    cost = db.execute(select(CostEntry).where(CostEntry.project_id == pid)).scalars().one()
    assert cost.amount_usd is None
    assert cost.fx_rate_usd is None


# --------------------------------------------------------------------------- #
# Backfill: correctness, idempotency, pre-history left null
# --------------------------------------------------------------------------- #
def test_backfill_populates_idempotently(client, seed, db):
    pid = _login_dir(client, seed)
    cid = seed["a"]["company"].id
    # Create legacy rows BEFORE any rate exists -> USD left null.
    c_id = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "64000", "vat_rate": "0",
    }).json()["data"]["id"]
    i_id = client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HAK-BF-1", "invoice_date": "2025-02-01",
        "amount_try": "90000", "vat_rate": "0", "due_date": "2025-03-01",
    }).json()["data"]["id"]
    # A pre-history row whose date has no rate available.
    old_id = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2019-01-01", "cost_category": "other", "amount_try": "1000", "vat_rate": "0",
    }).json()["data"]["id"]

    # Now historical rates become available (but not for 2019).
    _seed_rate(db, "2025-03-01", "32.0000")
    _seed_rate(db, "2025-02-01", "30.0000")

    summary = fx_backfill.backfill_company(db, cid)
    assert summary["costs_updated"] == 1
    assert summary["invoices_updated"] == 1
    assert summary["costs_no_rate"] == 1   # the 2019 row

    db.expire_all()
    assert db.get(CostEntry, c_id).amount_usd == Decimal("2000.00")
    assert db.get(ClientInvoice, i_id).amount_usd == Decimal("3000.00")
    assert db.get(CostEntry, old_id).amount_usd is None  # pre-history left null

    # Idempotent: a second run changes nothing (everything already populated/flagged).
    summary2 = fx_backfill.backfill_company(db, cid)
    assert summary2["costs_updated"] == 0
    assert summary2["invoices_updated"] == 0
    assert summary2["costs_skipped"] == 1
    assert summary2["invoices_skipped"] == 1
    # The pre-history row stays null and is re-attempted (no rate) each run.
    assert summary2["costs_no_rate"] == 1
