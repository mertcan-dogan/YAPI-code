"""Project closeout lifecycle (Geçici Kabul → Kesin Hesap → Kesin Kabul).

Covers: the full stage lifecycle + the FREEZE rule (report_data frozen once at
kesin hesap), reopen reverses status + keeps history, the director-only gate
(non-director 403), the soft-lock (warns, never blocks), FROZEN STABILITY (the
snapshot is unchanged after underlying costs change post-freeze), and app-layer
cross-company isolation (RLS itself is proven on real Postgres in
test_rls_isolation_pg.py).
"""
from datetime import date

import pytest

from app.constants import (
    CLOSEOUT_GECICI_KABUL,
    CLOSEOUT_KESIN_HESAP,
    CLOSEOUT_KESIN_KABUL,
    ROLE_DIRECTOR,
    ROLE_FINANCE,
    ROLE_PROJECT_MANAGER,
    ROLE_SITE_MANAGER,
)
from app.models.closeout import ProjectCloseout


def _pid(seed, label="a"):
    return seed[label]["project"].id


def _director(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])


# --- Full lifecycle ---------------------------------------------------------
def test_full_lifecycle_freezes_at_kesin_hesap(client, seed, db):
    pid = _pid(seed)
    _director(client, seed)

    # Geçici Kabul — opens the closeout, marks the project completed.
    r = client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["closeout"]["stage"] == CLOSEOUT_GECICI_KABUL
    assert body["closeout"]["gecici_kabul_date"] == "2026-06-25"
    assert body["project_status"] == "completed"
    assert body["report_frozen"] is False
    proj = client.get(f"/api/v1/projects/{pid}").json()["data"]
    assert proj["status"] == "completed"
    assert proj["actual_end_date"] == "2026-06-25"

    # Kesin Hesap — FREEZES the report snapshot.
    r = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["closeout"]["stage"] == CLOSEOUT_KESIN_HESAP
    assert body["report_frozen"] is True
    assert body["summary"] is not None and body["summary"]["contract_value"]
    row = db.get(ProjectCloseout, __import__("uuid").UUID(body["closeout"]["id"]))
    assert row.report_data is not None and row.frozen_at is not None

    # Kesin Kabul — fully closed.
    r = client.post(f"/api/v1/projects/{pid}/closeout/kesin-kabul", json={"date": "2026-07-15"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["closeout"]["stage"] == CLOSEOUT_KESIN_KABUL


def test_invalid_stage_order_rejected(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    # Kesin hesap before geçici kabul.
    r = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    assert r.status_code == 409
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    # Kesin kabul before kesin hesap.
    r = client.post(f"/api/v1/projects/{pid}/closeout/kesin-kabul", json={"date": "2026-07-15"})
    assert r.status_code == 409


def test_cannot_open_two_active_closeouts(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    assert client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"}).status_code == 200
    r = client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-26"})
    assert r.status_code == 409


# --- Reopen reverses status + keeps history ---------------------------------
def test_reopen_reverses_status_and_keeps_history(client, seed, db):
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})

    r = client.post(f"/api/v1/projects/{pid}/reopen")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["project_status"] == "active"
    # The project is active again, and no active closeout remains.
    assert client.get(f"/api/v1/projects/{pid}").json()["data"]["status"] == "active"
    assert client.get(f"/api/v1/projects/{pid}/closeout").json()["data"]["closeout"] is None

    # The reopened row is KEPT in the archive (is_active False).
    archive = client.get(f"/api/v1/projects/{pid}/closeouts").json()["data"]
    assert len(archive) == 1 and archive[0]["is_active"] is False

    # A later re-close creates a brand-NEW active row (history accumulates).
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-08-01"})
    archive = client.get(f"/api/v1/projects/{pid}/closeouts").json()["data"]
    assert len(archive) == 2
    active = [c for c in archive if c["is_active"]]
    assert len(active) == 1 and active[0]["gecici_kabul_date"] == "2026-08-01"


# --- Director-only gate ------------------------------------------------------
@pytest.mark.parametrize("role", [ROLE_FINANCE, ROLE_PROJECT_MANAGER, ROLE_SITE_MANAGER])
@pytest.mark.parametrize("path", [
    "closeout/gecici-kabul", "closeout/kesin-hesap", "closeout/kesin-kabul", "reopen",
])
def test_stage_actions_are_director_only(client, seed, role, path):
    pid = _pid(seed)
    client.login(seed["a"]["users"][role])
    body = {} if path == "reopen" else {"date": "2026-06-25"}
    r = client.post(f"/api/v1/projects/{pid}/{path}", json=body)
    assert r.status_code == 403, f"{role} must not be able to {path}"


def test_nondirector_can_read_closeout(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    # Finance sees the status read-only (GET works; POST is 403 above).
    client.login(seed["a"]["users"][ROLE_FINANCE])
    r = client.get(f"/api/v1/projects/{pid}/closeout")
    assert r.status_code == 200
    assert r.json()["data"]["closeout"]["stage"] == CLOSEOUT_GECICI_KABUL


# --- Soft-lock: warn, never block -------------------------------------------
def test_soft_lock_warns_but_allows_cost_and_invoice(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})

    cost = client.post(f"/api/v1/projects/{pid}/costs", json={
        "cost_category": "material_steel", "description": "Demir", "amount_try": "1000",
        "vat_rate": "20", "entry_type": "actual", "entry_date": "2026-06-26",
    })
    assert cost.status_code == 200, cost.text  # NOT blocked
    assert "closeout_warning" in cost.json()["data"]

    inv = client.post(f"/api/v1/projects/{pid}/invoices", json={
        "invoice_number": "HK-001", "invoice_date": "2026-06-26", "due_date": "2026-07-26",
        "amount_try": "5000", "vat_rate": "20", "retention_amount_try": "0",
    })
    assert inv.status_code == 200, inv.text  # NOT blocked
    assert "closeout_warning" in inv.json()["data"]


# --- Frozen stability: snapshot never moves after freeze --------------------
def test_frozen_report_stable_after_underlying_cost_change(client, seed, db):
    import copy

    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    frozen = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    assert frozen.status_code == 200, frozen.text
    cid = __import__("uuid").UUID(frozen.json()["data"]["closeout"]["id"])
    snapshot_before = copy.deepcopy(db.get(ProjectCloseout, cid).report_data)
    actual_before = snapshot_before["total_actual"]

    # Simulate time elapsed since the freeze so the staleness comparison is
    # deterministic on SQLite (whose CURRENT_TIMESTAMP is only second-precise).
    # report_data is untouched — only the freeze instant is rolled back.
    from datetime import datetime, timezone
    co = db.get(ProjectCloseout, cid)
    co.frozen_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()

    # Add a cost AFTER the freeze (kept under the 500k approval threshold so it is
    # a counted actual, not a pending-approval entry).
    big = client.post(f"/api/v1/projects/{pid}/costs", json={
        "cost_category": "material_concrete", "description": "Beton", "amount_try": "100000",
        "vat_rate": "20", "entry_type": "actual", "entry_date": "2026-07-02",
    })
    assert big.status_code == 200, big.text
    assert big.json()["data"].get("pending_approval") in (False, None)

    # The FROZEN snapshot is byte-for-byte unchanged (no live recompute).
    db.expire_all()
    after = db.get(ProjectCloseout, cid).report_data
    assert after == snapshot_before
    assert after["total_actual"] == actual_before

    # A freshly-built live report WOULD differ — proving the freeze is real.
    from app.models.company import Company
    from app.services.reports import build_project_report_data

    project = seed["a"]["project"]
    company = db.get(Company, project.company_id)
    live = build_project_report_data(db, project, company)
    assert live["total_actual"] != actual_before

    # And the staleness flag flips so the director knows to re-freeze.
    status = client.get(f"/api/v1/projects/{pid}/closeout").json()["data"]
    assert status["report_stale"] is True


# --- Re-freeze after reopen captures FRESH data (not the stale snapshot) -----
def test_refreeze_after_reopen_reflects_new_costs(client, seed, db):
    """Money-critical: a reopened-then-recorrected project, re-closed, must freeze
    a NEW snapshot off live data — never reuse the first (now stale) report_data.
    Otherwise the final "Proje Sonu Raporu" would export pre-correction numbers."""
    pid = _pid(seed)
    _director(client, seed)

    # First close + freeze with no extra costs.
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    first = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    assert first.status_code == 200, first.text
    first_id = __import__("uuid").UUID(first.json()["data"]["closeout"]["id"])
    snap1 = db.get(ProjectCloseout, first_id).report_data
    actual1 = snap1["total_actual"]

    # Reopen, then book a real actual cost (under the 500k approval threshold so it
    # is counted, not pending), then re-close + re-freeze.
    assert client.post(f"/api/v1/projects/{pid}/reopen").status_code == 200
    booked = client.post(f"/api/v1/projects/{pid}/costs", json={
        "cost_category": "material_concrete", "description": "Düzeltme bedeli",
        "amount_try": "250000", "vat_rate": "20", "entry_type": "actual",
        "entry_date": "2026-07-10",
    })
    assert booked.status_code == 200, booked.text
    assert booked.json()["data"].get("pending_approval") in (False, None)

    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-07-15"})
    second = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-20"})
    assert second.status_code == 200, second.text
    second_id = __import__("uuid").UUID(second.json()["data"]["closeout"]["id"])
    assert second_id != first_id  # a brand-new row, not the archived one
    snap2 = db.get(ProjectCloseout, second_id).report_data

    # The NEW snapshot reflects the post-reopen cost; the OLD one is untouched.
    assert snap2["total_actual"] != actual1
    assert db.get(ProjectCloseout, first_id).report_data["total_actual"] == actual1

    # History holds two distinct frozen reports (one archived, one active).
    archive = client.get(f"/api/v1/projects/{pid}/closeouts").json()["data"]
    assert len(archive) == 2
    assert all(c["report_frozen"] for c in archive)
    actives = [c for c in archive if c["is_active"]]
    assert len(actives) == 1 and actives[0]["id"] == str(second_id)


# --- PDF: 404 before freeze, application/pdf after --------------------------
def test_report_pdf_404_before_freeze_then_pdf(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    # Not frozen yet → 404.
    assert client.get(f"/api/v1/projects/{pid}/closeout/report.pdf").status_code == 404
    client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    r = client.get(f"/api/v1/projects/{pid}/closeout/report.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


# --- Re-freeze of a stale report (director regenerates in place) ------------
def test_director_can_refreeze_stale_report_in_place(client, seed, db):
    """The "Yeniden Dondur" path: once frozen, a director may re-POST kesin-hesap
    to regenerate report_data from current live data (stage stays kesin_hesap, no
    new row). Kesin kabul (fully closed) then blocks further re-freeze."""
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    first = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    cid = __import__("uuid").UUID(first.json()["data"]["closeout"]["id"])
    actual1 = db.get(ProjectCloseout, cid).report_data["total_actual"]

    # Book a counted actual, then RE-FREEZE (same endpoint, still stage kesin_hesap).
    client.post(f"/api/v1/projects/{pid}/costs", json={
        "cost_category": "material_concrete", "description": "Beton", "amount_try": "120000",
        "vat_rate": "20", "entry_type": "actual", "entry_date": "2026-07-05",
    })
    refreeze = client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-06"})
    assert refreeze.status_code == 200, refreeze.text
    assert refreeze.json()["data"]["closeout"]["id"] == str(cid)  # SAME row, not a new one
    assert refreeze.json()["data"]["closeout"]["stage"] == CLOSEOUT_KESIN_HESAP
    db.expire_all()
    assert db.get(ProjectCloseout, cid).report_data["total_actual"] != actual1  # regenerated

    # Once fully closed (kesin kabul), re-freeze is rejected.
    client.post(f"/api/v1/projects/{pid}/closeout/kesin-kabul", json={"date": "2026-07-10"})
    assert client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-11"}).status_code == 409


# --- PDF export policy: site managers cannot export (matches reports.py) -----
def test_report_pdf_export_blocked_for_site_manager(client, seed):
    pid = _pid(seed)
    _director(client, seed)
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    # Site manager is blocked from the export (403), same as /reports/project.
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    assert client.get(f"/api/v1/projects/{pid}/closeout/report.pdf").status_code == 403
    # Finance (an invoice-creator role, non-director) CAN export.
    client.login(seed["a"]["users"][ROLE_FINANCE])
    assert client.get(f"/api/v1/projects/{pid}/closeout/report.pdf").status_code == 200


def test_archive_pdf_serves_specific_row(client, seed):
    """Each archived closeout's frozen report is individually retrievable."""
    pid = _pid(seed)
    _director(client, seed)
    # Freeze, reopen (archives row #1), re-close + freeze (row #2 active).
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-01"})
    client.post(f"/api/v1/projects/{pid}/reopen")
    client.post(f"/api/v1/projects/{pid}/closeout/gecici-kabul", json={"date": "2026-07-15"})
    client.post(f"/api/v1/projects/{pid}/closeout/kesin-hesap", json={"date": "2026-07-20"})

    archive = client.get(f"/api/v1/projects/{pid}/closeouts").json()["data"]
    frozen_rows = [c for c in archive if c["report_frozen"]]
    assert len(frozen_rows) == 2
    for row in frozen_rows:
        r = client.get(f"/api/v1/projects/{pid}/closeouts/{row['id']}/report.pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"
    # Unknown closeout id under this project → 404.
    bad = __import__("uuid").uuid4()
    assert client.get(f"/api/v1/projects/{pid}/closeouts/{bad}/report.pdf").status_code == 404


# --- App-layer cross-company isolation (RLS proven on real PG) --------------
def test_cross_company_closeout_is_not_visible(client, seed):
    a_pid = _pid(seed, "a")
    # Company A director opens a closeout.
    _director(client, seed, "a")
    client.post(f"/api/v1/projects/{a_pid}/closeout/gecici-kabul", json={"date": "2026-06-25"})
    # Company B director cannot read A's project closeout (404, not a leak).
    _director(client, seed, "b")
    assert client.get(f"/api/v1/projects/{a_pid}/closeout").status_code == 404
    assert client.post(f"/api/v1/projects/{a_pid}/reopen").status_code == 404
