"""CR-032 §5/§7 — Report Studio API: GET /studio/catalog + POST /studio/run.

Catalog shape (public fields only), run happy-paths (line/bar/kpi/table), 422 on
a malformed spec, auth required, and company scoping (the engine takes company_id
from the authenticated user — NEVER the body). Real-RLS isolation for the base
tables is covered separately by test_rls_isolation_pg.py (CR-040); here we prove
the engine's app-level company filter under SQLite.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.client_invoice import ClientInvoice
from app.models.cost_entry import CostEntry
from app.services.studio.catalog import PUBLIC_KEYS

D = Decimal


def _cost(db, p, amount, uid, d=date(2026, 1, 10)):
    amt = D(str(amount))
    db.add(CostEntry(
        project_id=p.id, company_id=p.company_id, entry_date=d, cost_category="material_steel",
        amount_try=amt, vat_amount_try=D("0"), total_with_vat_try=amt,
        payment_status="unpaid", entry_type="actual", created_by=uid,
    ))
    db.commit()


def _login(client, seed, label="a"):
    client.login(seed[label]["users"][ROLE_DIRECTOR])
    return seed[label]["project"]


# --------------------------------------------------------------------------- #
# GET /studio/catalog
# --------------------------------------------------------------------------- #
def test_catalog_shape_public_fields_only(client, seed):
    _login(client, seed)
    r = client.get("/api/v1/studio/catalog")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert isinstance(data["dimensions"], list) and isinstance(data["metrics"], list)
    # ONLY public keys leave the API — the internal source/grain mapping never leaks.
    # Metrics additionally carry the derived public `windowed` flag (CR-033).
    for entry in data["dimensions"]:
        assert set(entry.keys()) <= set(PUBLIC_KEYS)
    for entry in data["metrics"]:
        assert set(entry.keys()) <= set(PUBLIC_KEYS) | {"windowed"}
    for entry in data["dimensions"] + data["metrics"]:
        assert "source" not in entry and "grain" not in entry and "basis" not in entry
    by_id = {m["id"]: m for m in data["metrics"]}
    assert by_id["dso"]["status"] == "coming_soon"
    assert by_id["schedule_progress"]["status"] == "coming_soon"
    assert by_id["cost_try"]["status"] == "available"
    # windowed (CR-033): cost-line/cash window; project/unit are whole-project.
    assert by_id["cost_try"]["windowed"] is True
    assert by_id["cash_in"]["windowed"] is True
    assert by_id["revenue"]["windowed"] is False
    assert by_id["margin_pct_current"]["windowed"] is False
    # Cut items are absent entirely (not coming_soon).
    ids = {e["id"] for e in data["dimensions"] + data["metrics"]}
    assert {"block_phase", "currency", "unit", "ar_aging"}.isdisjoint(ids)


def test_catalog_requires_auth(client, seed):
    assert client.get("/api/v1/studio/catalog").status_code == 401


# --------------------------------------------------------------------------- #
# POST /studio/run
# --------------------------------------------------------------------------- #
def test_run_requires_auth(client, seed):
    assert client.post("/api/v1/studio/run", json={"metrics": ["cost_try"]}).status_code == 401


def test_run_happy_paths_all_viz(client, seed, db):
    p = _login(client, seed)
    _cost(db, p, "120000", seed["a"]["users"][ROLE_DIRECTOR].id)

    kpi = client.post("/api/v1/studio/run", json={"viz": "kpi", "metrics": ["cost_try"]})
    assert kpi.status_code == 200, kpi.text
    assert kpi.json()["data"]["totals"]["metrics"]["cost_try"] == 120000.0

    table = client.post("/api/v1/studio/run", json={
        "viz": "table", "metrics": ["cost_try"], "dimensions": ["project"]})
    tb = table.json()["data"]
    assert table.status_code == 200
    assert "series" not in tb and len(tb["rows"]) == 1
    assert [c["id"] for c in tb["columns"]] == ["project", "cost_try"]

    line = client.post("/api/v1/studio/run", json={
        "viz": "line", "metrics": ["cost_try"], "dimensions": ["month"],
        "chart": {"x": "month", "y_left": ["cost_try"]}})
    ln = line.json()["data"]
    assert line.status_code == 200 and ln["series"][0]["metric"] == "cost_try"

    bar = client.post("/api/v1/studio/run", json={
        "viz": "bar", "metrics": ["cost_try"], "dimensions": ["cost_category"]})
    assert bar.status_code == 200 and "series" in bar.json()["data"]


def test_run_bad_spec_returns_422(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/studio/run", json={"metrics": []})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_run_company_scoped_a_vs_b(client, seed, db):
    pa, pb = seed["a"]["project"], seed["b"]["project"]
    _cost(db, pa, "100000", seed["a"]["users"][ROLE_DIRECTOR].id)
    _cost(db, pb, "555555", seed["b"]["users"][ROLE_DIRECTOR].id)

    _login(client, seed, "a")
    a = client.post("/api/v1/studio/run", json={"metrics": ["cost_try"]}).json()["data"]
    assert a["totals"]["metrics"]["cost_try"] == 100000.0

    _login(client, seed, "b")
    b = client.post("/api/v1/studio/run", json={"metrics": ["cost_try"]}).json()["data"]
    assert b["totals"]["metrics"]["cost_try"] == 555555.0


def test_run_ignores_company_id_in_body(client, seed, db):
    """company_id is taken from the authenticated user; a body-supplied one is
    ignored (no cross-tenant read)."""
    pa, pb = seed["a"]["project"], seed["b"]["project"]
    _cost(db, pa, "100000", seed["a"]["users"][ROLE_DIRECTOR].id)
    _cost(db, pb, "555555", seed["b"]["users"][ROLE_DIRECTOR].id)

    _login(client, seed, "a")
    # Attempt to spoof company B via the body — must be ignored.
    r = client.post("/api/v1/studio/run", json={
        "metrics": ["cost_try"], "company_id": str(pb.company_id)})
    assert r.status_code == 200
    assert r.json()["data"]["totals"]["metrics"]["cost_try"] == 100000.0  # still company A
