"""CR-023: committed-cost relief — the no-double-count invariant.

The critical rule (same discipline as CR-031): a commitment and its linked
invoice(s) must NEVER both count toward exposure. Always:

    total_committed_exposure == total_actual + Σ open_commitment

covering partial billing, full relief, and over-invoice.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.calculations import compute_project_financials
from app.calculations.project_financials import open_commitment, relief_by_commitment
from app.constants import ROLE_DIRECTOR, ROLE_FINANCE

D = Decimal


def _project(**over):
    base = {
        "contract_value_try": D("1000000"),
        "original_budget_try": D("800000"),
        "approved_variations_try": D("0"),
        "start_date": date(2025, 1, 1),
        "planned_end_date": date(2025, 12, 31),
        "target_margin_pct": D("15"),
        "completion_pct": D("50"),
    }
    base.update(over)
    return base


def _committed(cid, amount, cat="material_steel"):
    return {
        "id": cid, "commitment_id": None,
        "amount_try": D(amount), "total_with_vat_try": D(amount) * D("1.2"),
        "amount_paid_try": D("0"), "entry_type": "committed",
        "payment_status": "unpaid", "payment_due_date": None, "date_paid": None,
        "cost_category": cat,
    }


def _actual(amount, commitment_id=None, cat="material_steel"):
    return {
        "id": uuid.uuid4(), "commitment_id": commitment_id,
        "amount_try": D(amount), "total_with_vat_try": D(amount) * D("1.2"),
        "amount_paid_try": D("0"), "entry_type": "actual",
        "payment_status": "unpaid", "payment_due_date": None, "date_paid": None,
        "cost_category": cat,
    }


def _assert_invariant(fin):
    """exposure == actual + open committed — the core no-double-count rule."""
    assert fin["total_committed_exposure_try"] == (
        fin["total_actual_try"] + fin["total_open_committed_try"]
    )


# --------------------------------------------------------------------------
# Engine-level (pure dicts) — partial / full / over-invoice
# --------------------------------------------------------------------------
def test_partial_relief_no_double_count():
    # Commit 100k, invoice 60k linked → open 40k. Exposure = 60k actual + 40k open
    # = 100k (NOT 160k).
    cid = uuid.uuid4()
    costs = [_committed(cid, "100000"), _actual("60000", commitment_id=cid)]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_actual_try"] == D("60000.00")
    assert fin["total_open_committed_try"] == D("40000.00")
    assert fin["total_committed_exposure_try"] == D("100000.00")
    # remaining = revised 800k − exposure 100k.
    assert fin["remaining_budget_try"] == D("700000.00")
    _assert_invariant(fin)


def test_full_relief_no_double_count():
    # Commit 100k, invoice 60k + 40k linked → open 0, exposure = 100k actual.
    cid = uuid.uuid4()
    costs = [
        _committed(cid, "100000"),
        _actual("60000", commitment_id=cid),
        _actual("40000", commitment_id=cid),
    ]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_actual_try"] == D("100000.00")
    assert fin["total_open_committed_try"] == D("0.00")
    assert fin["total_committed_exposure_try"] == D("100000.00")
    assert fin["remaining_budget_try"] == D("700000.00")
    _assert_invariant(fin)


def test_over_invoice_no_double_count():
    # Commit 100k, invoice 120k linked (overrun) → open clamps to 0, exposure =
    # 120k actual (the 20k excess is ordinary extra actual, never negative open).
    cid = uuid.uuid4()
    costs = [_committed(cid, "100000"), _actual("120000", commitment_id=cid)]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_actual_try"] == D("120000.00")
    assert fin["total_open_committed_try"] == D("0.00")
    assert fin["total_committed_exposure_try"] == D("120000.00")
    assert fin["remaining_budget_try"] == D("680000.00")
    _assert_invariant(fin)


def test_open_commitment_helper_clamps_at_zero():
    cid = uuid.uuid4()
    costs = [_committed(cid, "100000"), _actual("120000", commitment_id=cid)]
    relief = relief_by_commitment(costs)
    assert open_commitment(costs[0], relief) == D("0")


def test_unlinked_commitment_is_fully_open():
    # An equipment-style committed entry with NO linked actual is fully open and in
    # exposure exactly once.
    costs = [_committed(uuid.uuid4(), "75000")]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_open_committed_try"] == D("75000.00")
    assert fin["total_committed_exposure_try"] == D("75000.00")
    _assert_invariant(fin)


def test_unlinked_actual_double_counts_by_design():
    # The spec's flagged risk: a commitment AND a separate actual for the same work
    # with NO link DO both count — exposure = 100k open + 80k actual = 180k. This is
    # exactly why linking matters; the invariant still holds (open is unrelieved).
    costs = [_committed(uuid.uuid4(), "100000"), _actual("80000", commitment_id=None)]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    assert fin["total_open_committed_try"] == D("100000.00")
    assert fin["total_actual_try"] == D("80000.00")
    assert fin["total_committed_exposure_try"] == D("180000.00")
    _assert_invariant(fin)


def test_forecast_includes_open_committed():
    # No budget rows; commit 200k, invoice 50k linked → open 150k. Forecast must be
    # at least actual + open = 50k + 150k = 200k (open commitments are money you
    # WILL spend), and margin reflects it.
    cid = uuid.uuid4()
    costs = [_committed(cid, "200000"), _actual("50000", commitment_id=cid)]
    fin = compute_project_financials(_project(), costs, [], [], today=date(2025, 6, 1))
    exposure = fin["total_actual_try"] + fin["total_open_committed_try"]
    assert fin["forecast_final_cost_try"] >= exposure
    assert fin["forecast_final_cost_try"] == D("200000.00")
    # margin = (1,000,000 − 200,000) / 1,000,000 = 80%.
    assert fin["margin_pct"] == D("80.00")
    _assert_invariant(fin)


def test_category_row_reconciles_revised():
    # Per-category: revised = invoiced + open_committed + remaining (clean split).
    cid = uuid.uuid4()
    costs = [_committed(cid, "100000"), _actual("60000", commitment_id=cid)]
    budgets = [{"cost_category": "material_steel", "original_budget_try": D("300000"),
                "approved_variations_try": D("0"), "forecast_final_try": None}]
    fin = compute_project_financials(_project(), costs, [], budgets, today=date(2025, 6, 1))
    steel = next(c for c in fin["categories"] if c["cost_category"] == "material_steel")
    assert steel["invoiced_try"] == D("60000.00")
    assert steel["open_committed_try"] == D("40000.00")
    assert steel["exposure_try"] == D("100000.00")
    assert steel["remaining_try"] == D("200000.00")  # 300k − 100k
    assert steel["invoiced_try"] + steel["open_committed_try"] + steel["remaining_try"] == steel["revised_budget_try"]


# --------------------------------------------------------------------------
# API-level — validation, scoping, relief flow, endpoint
# --------------------------------------------------------------------------
def _mk_commitment(client, pid, amount="100000", cat="material_steel", **extra):
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-02-01", "entry_type": "committed", "cost_category": cat,
        "amount_try": amount, "vat_rate": "20", **extra,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_invoice_against_commitment_relief_flow(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    commit = _mk_commitment(client, pid, "100000", po_number="PO-42", expected_date="2025-03-01")
    assert commit["po_number"] == "PO-42"

    # Link a 60k invoice (partial).
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "60000", "vat_rate": "20", "invoice_number": "F-1",
        "commitment_id": commit["id"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["commitment_id"] == commit["id"]

    # Commitments endpoint shows 40k open, 60k invoiced.
    cs = client.get(f"/api/v1/projects/{pid}/commitments").json()["data"]["commitments"]
    row = next(c for c in cs if c["id"] == commit["id"])
    assert row["amount_try"] == "100000.00"
    assert row["invoiced_try"] == "60000.00"
    assert row["open_try"] == "40000.00"
    assert row["invoice_count"] == 1
    assert row["fully_relieved"] is False

    # Dashboard budget totals: exposure 100k (NOT 160k), açık taahhüt 40k.
    budget = client.get(f"/api/v1/projects/{pid}/budget").json()["data"]["totals"]
    assert budget["invoiced_try"] == "60000.00"
    assert budget["open_committed_try"] == "40000.00"
    assert budget["exposure_try"] == "100000.00"

    # Fully relieve it.
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-04-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "40000", "vat_rate": "20", "commitment_id": commit["id"],
    })
    cs = client.get(f"/api/v1/projects/{pid}/commitments?open_only=true").json()["data"]["commitments"]
    assert all(c["id"] != commit["id"] for c in cs)  # no longer open


def test_commitment_cross_project_rejected(client, seed):
    # A commitment in company B's project cannot be linked from company A.
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    pid_b = seed["b"]["project"].id
    commit_b = _mk_commitment(client, pid_b, "50000")

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid_a = seed["a"]["project"].id
    r = client.post(f"/api/v1/projects/{pid_a}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "10000", "vat_rate": "20", "commitment_id": commit_b["id"],
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_COMMITMENT"


def test_link_to_non_committed_rejected(client, seed):
    client.login(seed["a"]["users"][ROLE_FINANCE])
    pid = seed["a"]["project"].id
    # Create a plain actual, then try to link another actual to it.
    actual = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "10000", "vat_rate": "20",
    }).json()["data"]
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-02", "entry_type": "actual", "cost_category": "material_steel",
        "amount_try": "5000", "vat_rate": "20", "commitment_id": actual["id"],
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_COMMITMENT"


def test_committed_entry_cannot_carry_link(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    commit = _mk_commitment(client, pid, "100000")
    r = client.post(f"/api/v1/projects/{pid}/costs", json={
        "entry_date": "2025-03-01", "entry_type": "committed", "cost_category": "material_steel",
        "amount_try": "5000", "vat_rate": "20", "commitment_id": commit["id"],
    })
    assert r.status_code == 422  # only actuals may link
