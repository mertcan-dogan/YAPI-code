"""CR-019-D — consolidated pass: gap-fillers + ONE end-to-end flow.

Fills the two §4 gaps the A/B tests left implicit (an OMITTED weight defaults to 1;
a forged company_id in the create body is ignored), then runs a single end-to-end
integration test spanning create → dashboard rollup → complete → re-derive, with
THE separate-lanes guard across the whole flow (every monetary figure
byte-identical AND zero cost/invoice rows created) plus company isolation.

Dialect-safe (runs on in-memory SQLite).
"""
import json
import uuid

from sqlalchemy import func, select

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.models.project_milestone import ProjectMilestone

API = "/api/v1"

# Far past/future so overdue/upcoming are deterministic regardless of run date.
PAST = "2020-03-01"
FUT_EARLY = "2099-02-01"
FUT_LATE = "2099-09-01"

# Every monetary surface the dashboard exposes — must never move with milestones.
MONEY_KEYS = ["financials", "forecast_at_completion", "margin_bridge", "usd", "financing", "cashflow"]


def _dash(client, pid) -> dict:
    r = client.get(f"{API}/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _money_snapshot(client, pid) -> str:
    d = _dash(client, pid)
    return json.dumps({k: d[k] for k in MONEY_KEYS}, sort_keys=True)


def _mk(client, pid, **kw):
    r = client.post(f"{API}/projects/{pid}/milestones", json={"title": "m", **kw})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _row_counts(session_factory, pid) -> tuple[int, int]:
    """Cost + invoice row counts via a FRESH session (sees committed data)."""
    s = session_factory()
    try:
        costs = s.execute(select(func.count()).select_from(CostEntry).where(CostEntry.project_id == pid)).scalar()
        invs = s.execute(select(func.count()).select_from(ClientInvoice).where(ClientInvoice.project_id == pid)).scalar()
        return int(costs or 0), int(invs or 0)
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Gap-fillers
# --------------------------------------------------------------------------- #
def test_omitted_weight_defaults_to_one(client, seed):
    # No `weight` key at all → defaults to 1; one of two done → 1/2 = 50%.
    pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    a = client.post(f"{API}/projects/{pid}/milestones", json={"title": "a"}).json()["data"]
    client.post(f"{API}/projects/{pid}/milestones", json={"title": "b"})
    assert a["weight"] in ("1", "1.0", "1.00")  # schema default surfaced
    client.put(f"{API}/projects/{pid}/milestones/{a['id']}", json={"status": "done"})
    assert client.get(f"{API}/projects/{pid}/milestones").json()["meta"]["schedule_progress_pct"] == "50.00"


def test_forged_company_id_in_body_is_ignored(client, seed, session_factory):
    # A client cannot set company_id from the request body — it's derived from the
    # project owner. A forged value (company B's) must be dropped.
    pid = seed["a"]["project"].id
    a_company = seed["a"]["company"].id
    b_company = seed["b"]["company"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(f"{API}/projects/{pid}/milestones", json={"title": "forge", "company_id": str(b_company)})
    assert r.status_code == 200, r.text
    mid = uuid.UUID(r.json()["data"]["id"])

    s = session_factory()
    try:
        m = s.get(ProjectMilestone, mid)
        assert str(m.company_id) == str(a_company)
        assert str(m.company_id) != str(b_company)
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# THE end-to-end flow
# --------------------------------------------------------------------------- #
def test_cr019_full_flow_e2e(client, seed, session_factory):
    a_pid = seed["a"]["project"].id
    client.login(seed["a"]["users"][ROLE_DIRECTOR])

    # --- Baseline: money snapshot + cost/invoice row counts BEFORE milestones ---
    money_before = _money_snapshot(client, a_pid)
    costs_before, invs_before = _row_counts(session_factory, a_pid)

    # --- Create weighted milestones across stages (2/3/5, mixed past/future) ---
    m_a = _mk(client, a_pid, title="Kazı", stage="Kaba", weight="2", planned_date=PAST, status="pending")        # overdue
    m_b = _mk(client, a_pid, title="Kolon", stage="Kaba", weight="3", planned_date=FUT_EARLY, status="pending")
    _mk(client, a_pid, title="Boya", stage="İnce", weight="5", planned_date=FUT_LATE, status="pending")

    # --- Dashboard rollup is EXACT before any completion (all pending → 0%) ---
    ms = _dash(client, a_pid)["milestones"]
    assert ms["schedule_progress_pct"] == "0.00"
    assert ms["total"] == 3 and ms["done"] == 0
    assert ms["overdue_count"] == 1          # only the past-dated pending one
    assert ms["next_deadline"] == FUT_EARLY  # earliest FUTURE not-done
    by_stage = {s["stage"]: s for s in ms["by_stage"]}
    assert by_stage["Kaba"] == {"stage": "Kaba", "progress_pct": "0.00", "done": 0, "total": 2, "deadline": PAST}
    assert by_stage["İnce"] == {"stage": "İnce", "progress_pct": "0.00", "done": 0, "total": 1, "deadline": FUT_LATE}

    # --- Complete two milestones (the overdue w2 + the future w3 in "Kaba") ---
    client.put(f"{API}/projects/{a_pid}/milestones/{m_a['id']}", json={"status": "done"})
    client.put(f"{API}/projects/{a_pid}/milestones/{m_b['id']}", json={"status": "done"})

    # --- Rollup re-derives; overdue + next_deadline update ---
    ms2 = _dash(client, a_pid)["milestones"]
    assert ms2["schedule_progress_pct"] == "50.00"   # (2+3)/10
    assert ms2["total"] == 3 and ms2["done"] == 2
    assert ms2["overdue_count"] == 0                 # the overdue one is now done
    assert ms2["next_deadline"] == FUT_LATE          # only the İnce w5 remains
    by_stage2 = {s["stage"]: s for s in ms2["by_stage"]}
    assert by_stage2["Kaba"] == {"stage": "Kaba", "progress_pct": "100.00", "done": 2, "total": 2, "deadline": None}
    assert by_stage2["İnce"] == {"stage": "İnce", "progress_pct": "0.00", "done": 0, "total": 1, "deadline": FUT_LATE}

    # --- THE separate-lanes guard ACROSS THE FULL FLOW (§0.2) ---
    money_after = _money_snapshot(client, a_pid)
    assert money_after == money_before, "No monetary figure may move when milestones change (separate lanes)"
    costs_after, invs_after = _row_counts(session_factory, a_pid)
    assert (costs_after, invs_after) == (costs_before, invs_before), "Milestones must create no cost/invoice rows"
    assert (costs_after, invs_after) == (0, 0)

    # --- Company isolation: B can't read A's milestones; B's block stays empty ---
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get(f"{API}/projects/{a_pid}/milestones").status_code == 404
    b_block = _dash(client, seed["b"]["project"].id)["milestones"]
    assert b_block["total"] == 0  # A's milestones never leaked into B
