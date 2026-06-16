"""CR-014-E: end-to-end USD tracking — the whole feature in one flow.

Seeded fx_rates only (no TCMB network; the conftest fixture disables live fetch).
Dialect-safe (SQLite). Spans: provisional snapshot on create -> lock at the
payment-date rate when paid -> project AND company dashboard USD totals = SUM of
the per-row snapshots (explicitly NOT total_try / a single today's rate) -> a row
with no resolvable rate stays null and is counted via usd_missing_count.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate


def _seed_rate(db, d: str, rate: str):
    db.add(FxRate(rate_date=date.fromisoformat(d), usd_try=Decimal(rate)))
    db.commit()


def test_usd_tracking_end_to_end(client, db, seed):
    a = seed["a"]
    pid = a["project"].id
    client.login(a["users"][ROLE_DIRECTOR])

    # (1) DIFFERENT rates on different dates.
    _seed_rate(db, "2025-03-01", "32.0000")  # entry date
    _seed_rate(db, "2025-05-01", "40.0000")  # later payment date — different rate

    # (2) Create a cost -> PROVISIONAL USD from the entry-date rate.
    cid = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "cost_category": "other", "amount_try": "64000", "vat_rate": "0",
    }).json()["data"]["id"]
    cost = db.execute(select(CostEntry).where(CostEntry.id == cid)).scalars().one()
    assert cost.payment_status != "paid"
    assert cost.fx_rate_usd == Decimal("32.0000")
    assert cost.amount_usd == Decimal("2000.00")  # 64000 / 32 (provisional)

    # (3) Mark paid on a later date -> re-snapshot + LOCK at the payment-date rate.
    r = client.put(f"/api/v1/projects/{pid}/costs/{cid}", json={"date_paid": "2025-05-01"})
    assert r.status_code == 200, r.text
    db.expire_all()
    cost = db.execute(select(CostEntry).where(CostEntry.id == cid)).scalars().one()
    assert cost.payment_status == "paid"
    assert cost.fx_rate_usd == Decimal("40.0000")
    assert cost.amount_usd == Decimal("1600.00")  # 64000 / 40 (locked) — not 2000 anymore

    # (5) A second row with NO resolvable rate -> amount_usd/fx_rate_usd stay null.
    cid2 = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2019-01-01", "cost_category": "other", "amount_try": "5000", "vat_rate": "0",
    }).json()["data"]["id"]
    cost2 = db.execute(select(CostEntry).where(CostEntry.id == cid2)).scalars().one()
    assert cost2.amount_usd is None and cost2.fx_rate_usd is None

    # SUM of the per-row snapshots (only the locked 1600.00 is non-null).
    snap_sum = sum(
        (Decimal(str(v)) for v in db.execute(
            select(CostEntry.amount_usd).where(CostEntry.project_id == pid)
        ).scalars().all() if v is not None),
        Decimal("0"),
    )
    assert snap_sum == Decimal("1600.00")

    # A naive total_try / single-today's-rate conversion gives a DIFFERENT number.
    total_try = db.execute(
        select(func.sum(CostEntry.amount_try)).where(CostEntry.project_id == pid)
    ).scalar_one()
    naive = (Decimal(str(total_try)) / Decimal("40.0000")).quantize(Decimal("0.01"))
    assert naive == Decimal("1725.00")  # 69000 / 40
    assert snap_sum != naive

    # (4a) PROJECT dashboard USD = locked snapshot sum, with the missing count,
    #      and NOT the naive conversion.
    pd = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["usd"]
    assert pd["costs"]["amount_usd"] == "1600.00"
    assert pd["costs"]["usd_missing_count"] == 1
    assert pd["costs"]["amount_usd"] != str(naive)

    # (4b) COMPANY dashboard USD = same snapshot sum (NOT total_try / today's rate).
    cd = client.get("/api/v1/dashboard").json()["data"]["usd"]
    assert cd["costs"]["amount_usd"] == "1600.00"
    assert cd["costs"]["usd_missing_count"] == 1
    assert cd["costs"]["amount_usd"] != str(naive)
