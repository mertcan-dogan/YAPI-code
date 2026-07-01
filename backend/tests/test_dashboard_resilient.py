"""Project dashboard resilience (silent-load-failure fix).

A single failing sub-section must NEVER 500 the whole dashboard (which left the
frontend in a perpetual skeleton). Each section degrades to null + a flag in
``degraded_sections``; TRY figures stay exact. Also covers the originally-reported
trigger: a CostEntry with a NULL ``amount_usd`` snapshot (its date had no FX rate)
must load fine — the USD paths are null-safe and the page returns 200.
"""
from datetime import date
from decimal import Decimal

from app.constants import ROLE_DIRECTOR
from app.models.cost_entry import CostEntry
from app.models.fx_rate import FxRate


def _null_usd_cost(project, director_id):
    return CostEntry(
        project_id=project.id, company_id=project.company_id, created_by=director_id,
        entry_date=date(2026, 1, 15), cost_category="material_other",
        amount_try=Decimal("10000.00"), vat_rate=Decimal("20"),
        vat_amount_try=Decimal("2000.00"), total_with_vat_try=Decimal("12000.00"),
        amount_usd=None, fx_rate_usd=None,  # NULL USD snapshot — the reported trigger
    )


def test_null_usd_project_dashboard_loads_200(client, db, seed):
    """Repro project: hakediş, non-residential, ONE cost with NULL amount_usd, an
    FX rate exists globally. Returns 200, TRY figures intact, USD section present
    and flagged (usd_missing_count)."""
    project = seed["a"]["project"]
    project.revenue_model = "hakedis"
    project.construction_net_m2 = None
    project.construction_gross_m2 = None
    db.add(project)
    db.add(FxRate(rate_date=date(2026, 6, 1), usd_try=Decimal("32.5000"), source="TCMB"))
    db.add(_null_usd_cost(project, seed["a"]["users"][ROLE_DIRECTOR].id))
    db.commit()

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{project.id}/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["degraded_sections"] == []  # nothing actually crashed
    # TRY figures exact.
    assert data["financials"] is not None
    assert data["financials"]["total_actual_with_vat_try"] == "12000.00"
    # USD section present + flagged (the null snapshot is counted, not crashed).
    assert data["usd"] is not None
    assert data["usd"]["costs"]["usd_missing_count"] >= 1


def test_failing_section_degrades_not_500(client, db, seed, monkeypatch):
    """If one sub-section computation raises, the page still returns 200: that
    section is null + listed in degraded_sections, and the OTHER sections (TRY
    financials) are intact."""
    from app.api import projects as projects_api

    def boom(*a, **k):
        raise RuntimeError("simulated computation failure")

    # Force the P&L section to blow up — historically this 500'd the whole page.
    monkeypatch.setattr(projects_api.sales_service, "project_pnl", boom)

    project = seed["a"]["project"]
    db.add(_null_usd_cost(project, seed["a"]["users"][ROLE_DIRECTOR].id))
    db.commit()

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{project.id}/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "pnl" in data["degraded_sections"]
    assert data["pnl"] is None
    # The rest of the page still rendered with exact TRY figures.
    assert data["financials"] is not None
    assert data["financials"]["total_actual_with_vat_try"] == "12000.00"
    assert data["investment_return"] is not None


def test_multiple_failures_each_flagged(client, db, seed, monkeypatch):
    from app.api import projects as projects_api

    def boom(*a, **k):
        raise ValueError("x")

    monkeypatch.setattr(projects_api.fin_service, "project_usd_totals", boom)
    monkeypatch.setattr(projects_api.financing_service, "compute_financing_cost", boom)

    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get(f"/api/v1/projects/{seed['a']['project'].id}/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(["usd", "financing"]).issubset(set(data["degraded_sections"]))
    assert data["usd"] is None and data["financing"] is None
    assert data["financials"] is not None  # unaffected
