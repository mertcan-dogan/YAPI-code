"""CR-016-D: consolidated end-to-end pass over the residential feature.

One flow spanning create → aggregates → edit (change/add/remove) → re-derive,
plus the non-residential leave-manual branch. The per-aspect coverage lives in
test_cr016a_schema.py (schema/validation) and test_cr016b_schedule.py (CRUD,
derivation, aggregates, isolation); this is the integration smoke that proves
they hold together. Dialect-safe (SQLite).
"""
from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.project import Project
from app.models.project_unit import ProjectUnit


def _residential_payload(**over):
    base = {
        "name": "Kentsel Dönüşüm Bloğu",
        "project_code": "PRJ-KD-1",
        "project_type": "urban_transformation",
        "revenue_model": "kat_karsiligi",
        "client_name": "Arsa Sahibi",
        "contract_value_try": "60000000",
        "original_budget_try": "45000000",
        "start_date": "2025-01-01",
        "planned_end_date": "2027-12-31",
    }
    base.update(over)
    return base


def _aggregates(client, pid):
    return client.get(f"/api/v1/projects/{pid}/dashboard").json()["data"]["residential"]


def test_residential_lifecycle_end_to_end(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    # --- CREATE: kat_karşılığı project with construction m² + a unit schedule ---
    r = client.post("/api/v1/projects", json=_residential_payload(
        construction_gross_m2="5000.00",
        construction_net_m2="4200.00",
        units=[
            {"unit_type": "2+1", "count": 8, "gross_m2_each": "110.00", "net_m2_each": "95.00", "sale_price_try": "4000000.00"},
            {"unit_type": "3+1", "count": 4, "gross_m2_each": "140.00", "net_m2_each": "120.00", "sale_price_try": "6000000.00"},
        ],
    ))
    assert r.status_code == 200, r.text
    project = r.json()["data"]
    pid = project["id"]
    assert project["construction_gross_m2"] == "5000.00"
    assert project["construction_net_m2"] == "4200.00"
    assert len(project["units"]) == 2

    # unit_count derived = 8 + 4 = 12.
    db.expire_all()
    assert db.get(Project, pid).unit_count == 12

    # Aggregates exact.
    agg = _aggregates(client, pid)
    assert agg["total_units"] == 12
    assert agg["total_sellable_gross_m2"] == "1440.00"   # 8*110 + 4*140
    assert agg["total_sellable_net_m2"] == "1240.00"     # 8*95 + 4*120
    assert agg["total_estimated_sales_try"] == "56000000.00"  # 8*4M + 4*6M

    # --- EDIT: change a count, add a new type, remove an existing type ---
    by_type = {u["unit_type"]: u for u in project["units"]}
    keep_id = by_type["2+1"]["id"]
    removed_id = by_type["3+1"]["id"]

    r = client.put(f"/api/v1/projects/{pid}", json={"units": [
        # keep + edit 2+1: count 8 -> 10
        {"id": keep_id, "unit_type": "2+1", "count": 10, "gross_m2_each": "110.00", "net_m2_each": "95.00", "sale_price_try": "4000000.00"},
        # add a brand-new 1+1 row
        {"unit_type": "1+1", "count": 5, "gross_m2_each": "65.00", "net_m2_each": "55.00", "sale_price_try": "2500000.00"},
        # (3+1 omitted -> soft-deleted)
    ]})
    assert r.status_code == 200, r.text

    db.expire_all()
    # The removed 3+1 row is soft-deleted (still present, flagged), not hard-deleted.
    removed = db.get(ProjectUnit, removed_id)
    assert removed is not None and removed.is_deleted is True and removed.deleted_at is not None
    # Live rows are exactly 2+1 (edited, same id) and the new 1+1.
    live = {u.unit_type: u for u in db.execute(
        select(ProjectUnit).where(ProjectUnit.project_id == pid, ProjectUnit.is_deleted.is_(False))
    ).scalars().all()}
    assert set(live) == {"2+1", "1+1"}
    assert str(live["2+1"].id) == keep_id and live["2+1"].count == 10

    # unit_count re-derived = 10 + 5 = 15.
    assert db.get(Project, pid).unit_count == 15

    # Aggregates updated.
    agg2 = _aggregates(client, pid)
    assert agg2["total_units"] == 15
    assert agg2["total_sellable_gross_m2"] == "1425.00"      # 10*110 + 5*65
    assert agg2["total_sellable_net_m2"] == "1225.00"        # 10*95 + 5*55
    assert agg2["total_estimated_sales_try"] == "52500000.00"  # 10*4M + 5*2.5M

    # --- NON-RESIDENTIAL: manual unit_count must NOT be zeroed (leave-manual) ---
    r = client.post("/api/v1/projects", json={
        "name": "Çevre Yolu", "project_code": "PRJ-YOL-1", "project_type": "road",
        "client_name": "Karayolları", "contract_value_try": "30000000",
        "original_budget_try": "24000000", "unit_count": 30,
        "start_date": "2025-03-01", "planned_end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    road_id = r.json()["data"]["id"]
    db.expire_all()
    road = db.get(Project, road_id)
    assert road.unit_count == 30           # manual value preserved, not derived to 0
    assert road.construction_gross_m2 is None
    assert road.units == []
    # And the road project's residential aggregates are an empty/zero schedule.
    road_agg = _aggregates(client, road_id)
    assert road_agg["total_units"] == 0
    assert road_agg["total_estimated_sales_try"] is None
