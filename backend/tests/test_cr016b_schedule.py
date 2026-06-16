"""CR-016-B: unit-schedule CRUD (via project create/update) + derived totals.

Persistence is wired through the `units` array on project create/update; granular
per-row endpoints are intentionally not added. Covers upsert, soft-delete of
removed rows, unit_count derivation (and that it stays manual without a schedule),
exact aggregate math, and company isolation.
"""
import uuid

from sqlalchemy import select

from app.constants import ROLE_DIRECTOR, ROLE_PROJECT_MANAGER
from app.models.project import Project
from app.models.project_unit import ProjectUnit


def _payload(**over):
    base = {
        "name": "Konut Projesi",
        "project_code": "PRJ-KONUT",
        "project_type": "building_residential",
        "client_name": "İşveren A.Ş.",
        "contract_value_try": "2000000",
        "original_budget_try": "1600000",
        "start_date": "2025-01-01",
        "planned_end_date": "2025-12-31",
    }
    base.update(over)
    return base


def _unit(**over):
    base = {"unit_type": "2+1", "count": 10, "gross_m2_each": "100.00"}
    base.update(over)
    return base


def _create(client, **over):
    return client.post("/api/v1/projects", json=_payload(**over))


def _live(db, pid):
    return db.execute(
        select(ProjectUnit).where(
            ProjectUnit.project_id == pid, ProjectUnit.is_deleted.is_(False)
        )
    ).scalars().all()


# --------------------------------------------------------------------------- #
# Persist on create
# --------------------------------------------------------------------------- #
def test_units_persist_on_create(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = _create(client, units=[_unit(count=10), _unit(unit_type="3+1", count=4, gross_m2_each="140")])
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]
    rows = _live(db, pid)
    assert len(rows) == 2
    assert all(u.company_id == seed["a"]["company"].id for u in rows)


def test_unit_count_derived_on_create(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    # Manual unit_count in the body is overridden by the schedule sum.
    r = _create(client, unit_count=999,
                units=[_unit(count=10), _unit(unit_type="3+1", count=4, gross_m2_each="140")])
    pid = r.json()["data"]["id"]
    db.expire_all()
    assert db.get(Project, pid).unit_count == 14


# --------------------------------------------------------------------------- #
# unit_count stays manual when there is no schedule
# --------------------------------------------------------------------------- #
def test_unit_count_stays_manual_without_schedule(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = _create(client, unit_count=42)  # no units array
    pid = r.json()["data"]["id"]
    db.expire_all()
    assert db.get(Project, pid).unit_count == 42


def test_non_residential_create_unchanged(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = _create(client, name="Yol", project_code="PRJ-YOL", project_type="road")
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]
    assert _live(db, pid) == []


# --------------------------------------------------------------------------- #
# Update: upsert (add / edit existing by id) + soft-delete removed
# --------------------------------------------------------------------------- #
def test_update_upserts_and_soft_deletes(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=10), _unit(unit_type="1+1", count=5, gross_m2_each="60")]).json()["data"]["id"]
    rows = client.get(f"/api/v1/projects/{pid}").json()["data"]["units"]
    by_type = {u["unit_type"]: u for u in rows}
    keep_id = by_type["2+1"]["id"]

    # Keep+edit the 2+1 (count 10 -> 12), drop the 1+1, add a new 3+1.
    r = client.put(f"/api/v1/projects/{pid}", json={"units": [
        {"id": keep_id, "unit_type": "2+1", "count": 12, "gross_m2_each": "100.00"},
        {"unit_type": "3+1", "count": 3, "gross_m2_each": "150.00"},
    ]})
    assert r.status_code == 200, r.text

    db.expire_all()
    live = {u.unit_type: u for u in _live(db, pid)}
    assert set(live) == {"2+1", "3+1"}
    assert live["2+1"].id == uuid.UUID(keep_id)  # same row updated, not recreated
    assert live["2+1"].count == 12
    # The removed 1+1 is soft-deleted (still present, flagged).
    all_rows = db.execute(select(ProjectUnit).where(ProjectUnit.project_id == pid)).scalars().all()
    deleted = [u for u in all_rows if u.is_deleted]
    assert len(deleted) == 1 and deleted[0].unit_type == "1+1"
    # unit_count re-derived = 12 + 3.
    assert db.get(Project, pid).unit_count == 15


def test_update_without_units_leaves_schedule_untouched(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=7)]).json()["data"]["id"]
    # An unrelated update (no units key) must not touch the schedule or unit_count.
    r = client.put(f"/api/v1/projects/{pid}", json={"completion_pct": "25"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert len(_live(db, pid)) == 1
    assert db.get(Project, pid).unit_count == 7


def test_update_with_empty_units_clears_schedule(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=7)]).json()["data"]["id"]
    r = client.put(f"/api/v1/projects/{pid}", json={"units": []})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _live(db, pid) == []  # all soft-deleted


# --------------------------------------------------------------------------- #
# Aggregates (computed, exact) on the dashboard payload
# --------------------------------------------------------------------------- #
def test_dashboard_aggregates_exact(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[
        _unit(unit_type="2+1", count=10, gross_m2_each="100.00", net_m2_each="85.00", sale_price_try="3000000.00"),
        _unit(unit_type="3+1", count=4, gross_m2_each="140.00", net_m2_each="120.00", sale_price_try="4500000.00"),
    ]).json()["data"]["id"]
    agg = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["residential"]
    assert agg["total_units"] == 14
    # 10*100 + 4*140 = 1560 ; 10*85 + 4*120 = 1330
    assert agg["total_sellable_gross_m2"] == "1560.00"
    assert agg["total_sellable_net_m2"] == "1330.00"
    # 10*3,000,000 + 4*4,500,000 = 48,000,000
    assert agg["total_estimated_sales_try"] == "48000000.00"


def test_aggregates_sales_none_when_no_prices(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=5, gross_m2_each="80.00")]).json()["data"]["id"]
    agg = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["residential"]
    assert agg["total_units"] == 5
    assert agg["total_sellable_gross_m2"] == "400.00"
    assert agg["total_sellable_net_m2"] == "0.00"  # no net values supplied
    assert agg["total_estimated_sales_try"] is None


def test_dashboard_aggregates_zero_without_schedule(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client).json()["data"]["id"]
    agg = client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["residential"]
    assert agg["total_units"] == 0
    assert agg["total_sellable_gross_m2"] == "0.00"
    assert agg["total_estimated_sales_try"] is None


# --------------------------------------------------------------------------- #
# Company isolation / forged company_id
# --------------------------------------------------------------------------- #
def test_forged_company_id_in_body_ignored(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    forged = str(seed["b"]["company"].id)
    r = _create(client, units=[{**_unit(count=3), "company_id": forged}])
    assert r.status_code == 200, r.text
    pid = r.json()["data"]["id"]
    rows = _live(db, pid)
    assert len(rows) == 1
    assert rows[0].company_id == seed["a"]["company"].id  # caller's company, not the forged one


def test_company_b_cannot_edit_company_a_units(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=4)]).json()["data"]["id"]

    # Company B cannot even see the project (404), let alone edit its units.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    r = client.put(f"/api/v1/projects/{pid}", json={"units": [_unit(count=99)]})
    assert r.status_code == 404
    db.expire_all()
    assert _live(db, pid)[0].count == 4  # unchanged


def test_non_director_cannot_edit_units(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = _create(client, units=[_unit(count=4)]).json()["data"]["id"]
    # A PM may edit completion_pct only — not the unit schedule.
    client.login(seed["a"]["users"][ROLE_PROJECT_MANAGER])
    r = client.put(f"/api/v1/projects/{pid}", json={"units": [_unit(count=99)]})
    assert r.status_code == 403
    db.expire_all()
    assert _live(db, pid)[0].count == 4
