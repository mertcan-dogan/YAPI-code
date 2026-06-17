"""CR-019-A — project_milestones: table + CRUD + weighted SQL rollup.

Covers the schedule lane only. The critical separate-lanes guard (§0.2) is here:
adding/completing milestones must leave every monetary figure byte-identical.
"""
import json
from datetime import date

from sqlalchemy import inspect

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE, ROLE_PROJECT_MANAGER

API = "/api/v1"


def _ms(**over):
    base = {"title": "Temel kazısı", "weight": "1", "status": "pending"}
    base.update(over)
    return base


def _list(client, pid):
    r = client.get(f"{API}/projects/{pid}/milestones")
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Schema / migration parity (model drives SQLite test schema)
# --------------------------------------------------------------------------- #
def test_project_milestones_table_created(engine):
    insp = inspect(engine)
    assert insp.has_table("project_milestones")
    cols = {c["name"] for c in insp.get_columns("project_milestones")}
    assert {
        "id", "project_id", "company_id", "title", "stage", "planned_date",
        "weight", "status", "completed_date", "sort_order", "notes",
        "created_at", "updated_at", "is_deleted", "deleted_at",
    } <= cols


def test_project_milestones_composite_index(engine):
    insp = inspect(engine)
    indexed = {tuple(i["column_names"]) for i in insp.get_indexes("project_milestones")}
    assert ("company_id", "project_id") in indexed


def test_existing_project_unaffected(client, seed):
    # No milestones → empty list + a null/zero rollup (additive, non-blocking).
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    body = _list(client, seed["a"]["project"].id)
    assert body["data"] == []
    assert body["meta"]["schedule_progress_pct"] is None
    assert body["meta"]["total"] == 0 and body["meta"]["done"] == 0
    assert body["meta"]["by_stage"] == []


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_create_milestone_persists(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="Kaba inşaat", stage="Kaba İnşaat", planned_date="2025-06-30", weight="3"))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["title"] == "Kaba inşaat"
    assert d["stage"] == "Kaba İnşaat"
    assert d["planned_date"] == "2025-06-30"
    assert d["status"] == "pending"
    assert len(_list(client, pid)["data"]) == 1


def test_pm_may_create_milestone(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_PROJECT_MANAGER])
    r = client.post(f"{API}/projects/{pid}/milestones", json=_ms())
    assert r.status_code == 200, r.text


def test_finance_cannot_edit_milestones(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_FINANCE])
    r = client.post(f"{API}/projects/{pid}/milestones", json=_ms())
    assert r.status_code == 403


def test_update_milestone(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    mid = client.post(f"{API}/projects/{pid}/milestones", json=_ms()).json()["data"]["id"]
    r = client.put(f"{API}/projects/{pid}/milestones/{mid}", json={"title": "Yeni başlık", "weight": "5"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["title"] == "Yeni başlık"


def test_mark_complete_sets_status_and_completed_date(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    mid = client.post(f"{API}/projects/{pid}/milestones", json=_ms()).json()["data"]["id"]
    r = client.put(f"{API}/projects/{pid}/milestones/{mid}", json={"status": "done"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "done"
    assert d["completed_date"] == date.today().isoformat()


def test_soft_delete_excludes_from_list(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    mid = client.post(f"{API}/projects/{pid}/milestones", json=_ms()).json()["data"]["id"]
    r = client.delete(f"{API}/projects/{pid}/milestones/{mid}")
    assert r.status_code == 200, r.text
    assert _list(client, pid)["data"] == []


def test_reorder_via_sort_order(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    a = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="A", sort_order=0)).json()["data"]["id"]
    b = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="B", sort_order=1)).json()["data"]["id"]
    r = client.put(f"{API}/projects/{pid}/milestones/reorder", json={"items": [{"id": b, "sort_order": 0}, {"id": a, "sort_order": 1}]})
    assert r.status_code == 200, r.text
    order = [m["title"] for m in _list(client, pid)["data"]]
    assert order == ["B", "A"]


def test_invalid_status_rejected(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(f"{API}/projects/{pid}/milestones", json=_ms(status="archived"))
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Weighted rollup (SQL aggregation)
# --------------------------------------------------------------------------- #
def test_weighted_rollup_overall(client, seed):
    # weights 2/3/5, only the "2" done → 2/10 = 20%.
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    m2 = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="w2", weight="2")).json()["data"]["id"]
    client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="w3", weight="3"))
    client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="w5", weight="5"))
    client.put(f"{API}/projects/{pid}/milestones/{m2}", json={"status": "done"})
    meta = _list(client, pid)["meta"]
    assert meta["schedule_progress_pct"] == "20.00"
    assert meta["total"] == 3 and meta["done"] == 1


def test_unset_or_zero_weight_defaults_to_one(client, seed):
    # Two zero-weight milestones, one done → each counts as 1 → 1/2 = 50%.
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    z = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="z1", weight="0")).json()["data"]["id"]
    client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="z2", weight="0"))
    client.put(f"{API}/projects/{pid}/milestones/{z}", json={"status": "done"})
    assert _list(client, pid)["meta"]["schedule_progress_pct"] == "50.00"


def test_rollup_divide_by_zero_guard(client, seed):
    # No milestones → guarded null, not an error.
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    meta = _list(client, pid)["meta"]
    assert meta["schedule_progress_pct"] is None
    assert meta["total"] == 0


def test_per_stage_rollup(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    # Stage A: two weight-1, one done → 50%. Stage B: one weight-4, done → 100%.
    a1 = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="a1", stage="A", weight="1")).json()["data"]["id"]
    client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="a2", stage="A", weight="1"))
    b1 = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="b1", stage="B", weight="4")).json()["data"]["id"]
    client.put(f"{API}/projects/{pid}/milestones/{a1}", json={"status": "done"})
    client.put(f"{API}/projects/{pid}/milestones/{b1}", json={"status": "done"})
    by_stage = {s["stage"]: s for s in _list(client, pid)["meta"]["by_stage"]}
    assert by_stage["A"]["progress_pct"] == "50.00" and by_stage["A"]["done"] == 1 and by_stage["A"]["total"] == 2
    assert by_stage["B"]["progress_pct"] == "100.00" and by_stage["B"]["total"] == 1


# --------------------------------------------------------------------------- #
# THE separate-lanes guard (§0.2): money figures must be byte-identical
# --------------------------------------------------------------------------- #
def _money_snapshot(client, pid) -> str:
    r = client.get(f"{API}/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    return json.dumps({"financials": d["financials"], "forecast_at_completion": d["forecast_at_completion"]}, sort_keys=True)


def test_milestones_do_not_touch_money(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    before = _money_snapshot(client, pid)

    m1 = client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="m1", weight="3")).json()["data"]["id"]
    client.post(f"{API}/projects/{pid}/milestones", json=_ms(title="m2", weight="2", stage="Kaba"))
    client.put(f"{API}/projects/{pid}/milestones/{m1}", json={"status": "done"})

    after = _money_snapshot(client, pid)
    assert before == after, "Milestones must not change any monetary figure (separate lanes §0.2)"


# --------------------------------------------------------------------------- #
# Company isolation
# --------------------------------------------------------------------------- #
def test_company_isolation_blocks_cross_company(client, seed):
    a_pid = seed["a"]["project"].id
    # Company A creates a milestone.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    mid = client.post(f"{API}/projects/{a_pid}/milestones", json=_ms()).json()["data"]["id"]

    # Company B cannot read or modify A's project milestones (404, existence hidden).
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"{API}/projects/{a_pid}/milestones").status_code == 404
    assert client.put(f"{API}/projects/{a_pid}/milestones/{mid}", json={"title": "hack"}).status_code == 404
    assert client.delete(f"{API}/projects/{a_pid}/milestones/{mid}").status_code == 404
