"""CR-019-B — the SCHEDULE-lane `milestones` block on the project dashboard.

Verifies the block's schedule_progress_pct / next_deadline / overdue_count /
by_stage across a past+future-date fixture, and re-asserts THE separate-lanes
guard at the dashboard level: every monetary figure in the payload is
byte-identical whether milestones exist/are completed or not (§0.2).
"""
import json

from app.constants import ROLE_DIRECTOR

API = "/api/v1"

# Far-past / far-future so overdue/upcoming assertions are deterministic on any run date.
PAST = "2020-01-01"
PAST2 = "2020-06-01"
FUT_EARLY = "2099-01-01"
FUT_LATE = "2099-06-01"

MONEY_KEYS = ["financials", "forecast_at_completion", "usd", "financing", "cashflow"]


def _dash(client, pid) -> dict:
    r = client.get(f"{API}/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _mk(client, pid, **kw):
    r = client.post(f"{API}/projects/{pid}/milestones", json={"title": "m", **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _seed_milestones(client, pid):
    # 4 milestones, default weight 1 each, 1 done → 25% progress.
    _mk(client, pid, title="overdue", status="pending", planned_date=PAST)          # overdue, ungrouped
    _mk(client, pid, title="done_past", status="done", planned_date=PAST2)          # done → not overdue
    _mk(client, pid, title="fut_early", status="in_progress", planned_date=FUT_EARLY, stage="Kaba")
    _mk(client, pid, title="fut_late", status="pending", planned_date=FUT_LATE, stage="Kaba")


def test_dashboard_has_milestones_block_when_empty(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    ms = _dash(client, pid)["milestones"]
    assert ms["schedule_progress_pct"] is None
    assert ms["total"] == 0 and ms["done"] == 0
    assert ms["next_deadline"] is None
    assert ms["overdue_count"] == 0
    assert ms["by_stage"] == []


def test_dashboard_milestones_progress_and_counts(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    _seed_milestones(client, pid)
    ms = _dash(client, pid)["milestones"]
    assert ms["schedule_progress_pct"] == "25.00"
    assert ms["total"] == 4 and ms["done"] == 1


def test_dashboard_next_deadline_is_earliest_future_not_done(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    _seed_milestones(client, pid)
    ms = _dash(client, pid)["milestones"]
    # Earliest FUTURE not-done deadline (the past one is overdue, not "next").
    assert ms["next_deadline"] == FUT_EARLY


def test_dashboard_overdue_count(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    _seed_milestones(client, pid)
    ms = _dash(client, pid)["milestones"]
    # Only the pending past-dated one is overdue; the done past-dated one is not.
    assert ms["overdue_count"] == 1


def test_dashboard_by_stage_block(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    _seed_milestones(client, pid)
    by_stage = {s["stage"]: s for s in _dash(client, pid)["milestones"]["by_stage"]}

    kaba = by_stage["Kaba"]
    assert kaba["total"] == 2 and kaba["done"] == 0
    assert kaba["progress_pct"] == "0.00"
    assert kaba["deadline"] == FUT_EARLY  # earliest not-done in the stage

    ungrouped = by_stage[None]
    assert ungrouped["total"] == 2 and ungrouped["done"] == 1
    assert ungrouped["progress_pct"] == "50.00"
    assert ungrouped["deadline"] == PAST  # nearest pending (overdue) date


# --------------------------------------------------------------------------- #
# THE separate-lanes guard at the dashboard level (§0.2)
# --------------------------------------------------------------------------- #
def _money_snapshot(client, pid) -> str:
    d = _dash(client, pid)
    return json.dumps({k: d[k] for k in MONEY_KEYS}, sort_keys=True)


def test_dashboard_money_unchanged_by_milestones(client, seed):
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    before = _money_snapshot(client, pid)
    _seed_milestones(client, pid)
    # Also complete one more to be sure completing a milestone moves no money.
    extra = _mk(client, pid, title="extra", status="pending", planned_date=FUT_LATE, weight="5")
    client.put(f"{API}/projects/{pid}/milestones/{extra['id']}", json={"status": "done"})

    after = _money_snapshot(client, pid)
    assert before == after, "Milestones must not change any monetary dashboard figure (§0.2)"


def test_milestones_block_does_not_add_money_keys(client, seed):
    # Sanity: the block carries only schedule fields (no ₺/USD/margin leakage).
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    _seed_milestones(client, pid)
    ms = _dash(client, pid)["milestones"]
    assert set(ms.keys()) == {"schedule_progress_pct", "total", "done", "next_deadline", "overdue_count", "by_stage"}
    for s in ms["by_stage"]:
        assert set(s.keys()) == {"stage", "progress_pct", "done", "total", "deadline"}
