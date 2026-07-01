"""CR-015-A: financing-cost settings (company defaults + project overrides).

Schema/settings only — financing defaults OFF, so there is no behavior change
yet. Covers the columns + safe defaults, the schemas, and the effective-value
resolver (project override → company default), both ways. SQLite-backed.
"""
from decimal import Decimal

from sqlalchemy import inspect

from app.constants import ROLE_DIRECTOR
from app.models.company import Company
from app.models.project import Project
from app.services import financing


# --------------------------------------------------------------------------- #
# Schema columns + safe defaults (off)
# --------------------------------------------------------------------------- #
def test_company_financing_columns_exist(engine):
    cols = {c["name"]: c for c in inspect(engine).get_columns("companies")}
    assert "financing_enabled" in cols
    assert "financing_annual_rate_pct" in cols and cols["financing_annual_rate_pct"]["nullable"]
    assert "financing_basis" in cols


def test_project_financing_override_columns_exist(engine):
    cols = {c["name"]: c for c in inspect(engine).get_columns("projects")}
    assert "financing_enabled_override" in cols and cols["financing_enabled_override"]["nullable"]
    assert "financing_annual_rate_pct_override" in cols and cols["financing_annual_rate_pct_override"]["nullable"]


def test_defaults_are_off(seed, db):
    company = seed["a"]["company"]
    project = seed["a"]["project"]
    db.refresh(company)
    db.refresh(project)
    assert company.financing_enabled is False
    assert company.financing_annual_rate_pct is None
    assert company.financing_basis == "cumulative"
    assert project.financing_enabled_override is None
    assert project.financing_annual_rate_pct_override is None


# --------------------------------------------------------------------------- #
# Effective-value resolution (project override → company default)
# --------------------------------------------------------------------------- #
def test_effective_inherits_company_default_when_no_override(seed, db):
    company = seed["a"]["company"]
    project = seed["a"]["project"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12.50")
    db.commit()

    assert financing.effective_financing_enabled(company, project) is True
    assert financing.effective_financing_rate(company, project) == Decimal("12.50")
    eff = financing.effective_financing(company, project)
    assert eff == {"enabled": True, "annual_rate_pct": Decimal("12.50"), "basis": "cumulative"}


def test_project_override_beats_company_default(seed, db):
    company = seed["a"]["company"]
    project = seed["a"]["project"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("12.50")
    # Project turns financing OFF and sets its own rate.
    project.financing_enabled_override = False
    project.financing_annual_rate_pct_override = Decimal("9.00")
    db.commit()

    assert financing.effective_financing_enabled(company, project) is False
    assert financing.effective_financing_rate(company, project) == Decimal("9.00")


def test_project_override_can_enable_when_company_off(seed, db):
    company = seed["a"]["company"]
    project = seed["a"]["project"]
    assert company.financing_enabled is False
    project.financing_enabled_override = True
    project.financing_annual_rate_pct_override = Decimal("15.00")
    db.commit()

    assert financing.effective_financing_enabled(company, project) is True
    assert financing.effective_financing_rate(company, project) == Decimal("15.00")


def test_resolver_without_project_uses_company(seed, db):
    company = seed["a"]["company"]
    company.financing_enabled = True
    company.financing_annual_rate_pct = Decimal("10.00")
    db.commit()
    assert financing.effective_financing_enabled(company, None) is True
    assert financing.effective_financing_rate(company, None) == Decimal("10.00")


# --------------------------------------------------------------------------- #
# API: settings expose + persist
# --------------------------------------------------------------------------- #
def test_company_out_exposes_financing(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    data = client.get("/api/v1/settings/company").json()["data"]
    assert data["financing_enabled"] is False
    assert data["financing_annual_rate_pct"] is None
    assert data["financing_basis"] == "cumulative"


def test_company_update_persists_financing(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put("/api/v1/settings/company", json={
        "financing_enabled": True, "financing_annual_rate_pct": "11.25", "financing_basis": "net",
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["financing_enabled"] is True
    assert float(d["financing_annual_rate_pct"]) == 11.25
    assert d["financing_basis"] == "net"


def test_company_update_rejects_invalid_basis(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put("/api/v1/settings/company", json={"financing_basis": "weekly"})
    assert r.status_code == 422


def test_project_create_accepts_financing_overrides(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json={
        "name": "Finansman Projesi", "project_code": "PRJ-FIN", "project_type": "road",
        "client_name": "İşveren", "contract_value_try": "1000000", "original_budget_try": "800000",
        "start_date": "2025-01-01", "planned_end_date": "2025-12-31",
        "financing_enabled_override": True, "financing_annual_rate_pct_override": "8.50",
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["financing_enabled_override"] is True
    assert d["financing_annual_rate_pct_override"] == "8.50"


def test_project_out_exposes_overrides_null_by_default(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    d = client.get(f"/api/v1/projects/{pid}").json()["data"]
    assert d["financing_enabled_override"] is None
    assert d["financing_annual_rate_pct_override"] is None


def test_project_update_sets_override(client, seed, db):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    r = client.put(f"/api/v1/projects/{pid}", json={"financing_annual_rate_pct_override": "7.75"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Project, pid).financing_annual_rate_pct_override == Decimal("7.75")


def test_existing_financial_outputs_unchanged_while_off(client, seed):
    """Dashboard still renders identically — financing defaults OFF (no new keys break it)."""
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    r = client.get(f"/api/v1/projects/{pid}/dashboard")
    assert r.status_code == 200, r.text
    # Sanity: company financing is off, so nothing in A touched actuals.
    assert seed["a"]["company"].financing_enabled is False
