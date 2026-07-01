"""Perf — per-session input cache + batch primer kill the redundant input loads.

Measures DB work as a query count (deterministic, environment-independent):
 - single project: the dashboard's project_financials + cashflow + forecast +
   margin_bridge load the inputs ONCE, not 4×;
 - many projects: prime_project_inputs batch-loads in 3 queries, then each
   project_financials adds ZERO input queries (the N+1 is gone);
 - correctness: a flush of a cost/invoice/budget row invalidates the cache, so a
   read-after-write recomputes from fresh rows.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.services import financials as fin


def _count_input_queries(db, fn) -> dict:
    counts = {"cost": 0, "invoice": 0, "budget": 0}
    engine = db.get_bind()

    def listener(conn, cursor, statement, params, context, executemany):
        s = statement.lower()
        if "from cost_entries" in s:
            counts["cost"] += 1
        if "from client_invoices" in s:
            counts["invoice"] += 1
        if "from budget_line_items" in s:
            counts["budget"] += 1

    event.listen(engine, "after_cursor_execute", listener)
    try:
        fn()
    finally:
        event.remove(engine, "after_cursor_execute", listener)
    return counts


def _add_cost(db, p, cid, uid, amount="1000"):
    db.add(CostEntry(
        project_id=p.id, company_id=cid, entry_date=date(2026, 1, 10), cost_category="other",
        supplier_name="X", amount_try=Decimal(amount), vat_amount_try=Decimal("0"),
        total_with_vat_try=Decimal(amount), payment_status="unpaid", entry_type="actual",
        created_by=uid,
    ))
    db.commit()


def _extra_projects(db, seed, n=2):
    cid = seed["a"]["company"].id
    pmid = seed["a"]["users"]["project_manager"].id
    out = [seed["a"]["project"]]
    for i in range(n):
        p = Project(
            company_id=cid, name=f"Ek Proje {i}", project_code=f"EK-{i}", project_type="road",
            client_name="İşveren", contract_value_try=1_000_000, original_budget_try=800_000,
            start_date=date(2025, 1, 1), planned_end_date=date(2025, 12, 31),
            project_manager_id=pmid,
        )
        db.add(p)
        out.append(p)
    db.commit()
    return out


# --------------------------------------------------------------------------- #
# Single project — the dashboard's 4 financials calls load inputs once
# --------------------------------------------------------------------------- #
def test_repeat_financials_second_call_is_pure_cache_hit(db, seed):
    p = seed["a"]["project"]
    _add_cost(db, p, seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id)

    c1 = _count_input_queries(db, lambda: fin.project_financials(db, p))
    assert c1["cost"] >= 1 and c1["budget"] >= 1  # first call loads

    # The other three dashboard calls + a repeat all hit the cache → 0 input reads.
    c2 = _count_input_queries(db, lambda: (
        fin.project_financials(db, p),
        fin.project_cashflow(db, p),
        fin.forecast_at_completion(db, p),
        fin.margin_bridge(db, p),
    ))
    assert c2 == {"cost": 0, "invoice": 0, "budget": 0}


def test_dashboard_flow_loads_inputs_once_per_table(db, seed):
    p = seed["a"]["project"]
    _add_cost(db, p, seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id)

    def flow():
        fin.project_financials(db, p)
        fin.project_cashflow(db, p)
        fin.forecast_at_completion(db, p)
        fin.margin_bridge(db, p)

    c = _count_input_queries(db, flow)
    # Each input table is read exactly once for the whole dashboard (was 2–4×).
    assert c == {"cost": 1, "invoice": 1, "budget": 1}


# --------------------------------------------------------------------------- #
# Many projects — batch primer kills the N+1
# --------------------------------------------------------------------------- #
def test_prime_batches_three_projects_in_three_queries(db, seed):
    projects = _extra_projects(db, seed, n=2)  # 3 total
    c = _count_input_queries(db, lambda: fin.prime_project_inputs(db, projects))
    assert c == {"cost": 1, "invoice": 1, "budget": 1}


def test_primed_financials_add_no_input_queries(db, seed):
    projects = _extra_projects(db, seed, n=2)
    fin.prime_project_inputs(db, projects)
    c = _count_input_queries(db, lambda: [fin.project_financials(db, p) for p in projects])
    # All three projects served from the primed cache → zero further input reads.
    assert c == {"cost": 0, "invoice": 0, "budget": 0}


# --------------------------------------------------------------------------- #
# Correctness — a write invalidates the cache (no stale read-after-write)
# --------------------------------------------------------------------------- #
def test_flush_invalidates_cache(db, seed):
    p = seed["a"]["project"]
    cid, uid = seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id

    f1 = fin.project_financials(db, p)            # caches inputs
    _add_cost(db, p, cid, uid, amount="5000")     # commit flushes a CostEntry → cache cleared
    f2 = fin.project_financials(db, p)            # must reload + reflect the new cost

    assert Decimal(f2["total_actual_try"]) > Decimal(f1["total_actual_try"])


# --------------------------------------------------------------------------- #
# Endpoint-level: GET /projects loads inputs once per table regardless of N
# (the N+1 fix). With 3 projects this is 3 input reads, not 9.
# --------------------------------------------------------------------------- #
def test_list_projects_endpoint_batches_input_loads(client, seed, db):
    cid, uid = seed["a"]["company"].id, seed["a"]["users"][ROLE_DIRECTOR].id
    projects = _extra_projects(db, seed, n=2)  # 3 total
    for p in projects:
        _add_cost(db, p, cid, uid)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    counts = {"cost": 0, "invoice": 0, "budget": 0}
    engine = db.get_bind()

    def listener(conn, cursor, statement, params, context, executemany):
        s = statement.lower()
        if "from cost_entries" in s:
            counts["cost"] += 1
        if "from client_invoices" in s:
            counts["invoice"] += 1
        if "from budget_line_items" in s:
            counts["budget"] += 1

    event.listen(engine, "after_cursor_execute", listener)
    try:
        r = client.get("/api/v1/projects")
    finally:
        event.remove(engine, "after_cursor_execute", listener)

    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 3
    # One batch query per input table for all 3 projects (was 3 per table = 9).
    assert counts == {"cost": 1, "invoice": 1, "budget": 1}
