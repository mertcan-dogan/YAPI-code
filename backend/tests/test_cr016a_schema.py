"""CR-016-A: residential schema — m² columns on projects + project_units table.

Schema/validation only. Persistence of the `units` schedule (upsert + unit_count
derivation + aggregates) lands in CR-016-B; here we verify the table/columns
exist, are additive/nullable, and the DTOs expose + validate residential details.
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from app.constants import ROLE_DIRECTOR, UNIT_TYPE_KEYS
from app.models import ProjectUnit
from app.schemas.project import ProjectCreate, ProjectOut, UnitScheduleIn


def _project_payload(**over):
    base = {
        "name": "Konut Projesi",
        "project_code": "PRJ-KONUT",
        "project_type": "building_residential",
        "client_name": "İşveren A.Ş.",
        "contract_value_try": "2000000",
        "original_budget_try": "1600000",
        "start_date": "2025-01-01",
        "planned_end_date": "2025-12-31",
    }
    base.update(over)
    return base


def _unit(**over):
    base = {"unit_type": "2+1", "count": 12, "gross_m2_each": "110.50"}
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Migration / model: table + columns exist, additive & nullable
# --------------------------------------------------------------------------- #
def test_project_units_table_created(engine):
    insp = inspect(engine)
    assert insp.has_table("project_units")
    cols = {c["name"] for c in insp.get_columns("project_units")}
    assert {
        "id", "project_id", "company_id", "unit_type", "custom_label", "count",
        "gross_m2_each", "net_m2_each", "sale_price_try", "notes",
        "created_at", "updated_at", "is_deleted", "deleted_at",
    } <= cols


def test_project_units_indexed_on_project_and_company(engine):
    insp = inspect(engine)
    indexed = {tuple(i["column_names"]) for i in insp.get_indexes("project_units")}
    assert ("project_id",) in indexed
    assert ("company_id",) in indexed


def test_projects_gains_nullable_m2_columns(engine):
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("projects")}
    assert "construction_gross_m2" in cols and cols["construction_gross_m2"]["nullable"]
    assert "construction_net_m2" in cols and cols["construction_net_m2"]["nullable"]


def test_existing_project_untouched_no_residential_details(seed, db):
    # The seeded road project has no m² and no units — additive, non-blocking.
    p = seed["a"]["project"]
    assert p.construction_gross_m2 is None
    assert p.construction_net_m2 is None
    assert p.units == []


def test_project_unit_persists_company_scoped(seed, db):
    a = seed["a"]
    u = ProjectUnit(
        project_id=a["project"].id, company_id=a["company"].id,
        unit_type="3+1", count=4, gross_m2_each=Decimal("140.00"),
    )
    db.add(u)
    db.commit()
    db.refresh(a["project"])
    assert len(a["project"].units) == 1
    assert a["project"].units[0].company_id == a["company"].id


# --------------------------------------------------------------------------- #
# UnitScheduleIn validation
# --------------------------------------------------------------------------- #
def test_all_preset_unit_types_accepted():
    for key in UNIT_TYPE_KEYS:
        over = {"unit_type": key}
        if key == "other":
            over["custom_label"] = "Sığınak"
        assert UnitScheduleIn(**_unit(**over)).unit_type == key


def test_invalid_unit_type_rejected():
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(unit_type="5+1"))


def test_other_requires_custom_label():
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(unit_type="other"))
    # With a label it validates.
    assert UnitScheduleIn(**_unit(unit_type="other", custom_label="Sığınak")).custom_label == "Sığınak"


def test_count_must_be_at_least_one():
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(count=0))


def test_gross_m2_must_be_positive():
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(gross_m2_each="0"))


def test_optional_net_and_price_reject_non_positive():
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(net_m2_each="-1"))
    with pytest.raises(ValidationError):
        UnitScheduleIn(**_unit(sale_price_try="0"))
    # None is allowed for both.
    ok = UnitScheduleIn(**_unit(net_m2_each=None, sale_price_try=None))
    assert ok.net_m2_each is None and ok.sale_price_try is None


# --------------------------------------------------------------------------- #
# DTO exposure
# --------------------------------------------------------------------------- #
def test_project_create_accepts_residential_details():
    dto = ProjectCreate(**_project_payload(
        construction_gross_m2="5000.00", construction_net_m2="4200.00",
        units=[_unit(), _unit(unit_type="1+1", count=8, gross_m2_each="65")],
    ))
    assert dto.construction_gross_m2 == Decimal("5000.00")
    assert len(dto.units) == 2


def test_project_create_units_default_empty():
    dto = ProjectCreate(**_project_payload())
    assert dto.units == []
    assert dto.construction_gross_m2 is None


def test_project_out_exposes_units_field():
    assert "units" in ProjectOut.model_fields
    assert "construction_gross_m2" in ProjectOut.model_fields
    assert "construction_net_m2" in ProjectOut.model_fields


# --------------------------------------------------------------------------- #
# Read path serialises an empty schedule (no regression to project read)
# --------------------------------------------------------------------------- #
def test_project_out_serialises_empty_units(seed):
    out = ProjectOut.model_validate(seed["a"]["project"])
    assert out.units == []
    assert out.construction_gross_m2 is None


# --------------------------------------------------------------------------- #
# Create endpoint stays green with units present (persistence deferred to CR-016-B)
# --------------------------------------------------------------------------- #
def test_create_endpoint_accepts_units(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_project_payload(
        construction_gross_m2="5000.00",
        units=[_unit(), _unit(unit_type="other", custom_label="Depo", count=3, gross_m2_each="30")],
    ))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["construction_gross_m2"] == "5000.00"
    # CR-016-B persists the schedule on create.
    assert len(data["units"]) == 2


def test_non_residential_create_unchanged(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_project_payload(
        name="Yol Projesi", project_code="PRJ-YOL", project_type="road"))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["construction_gross_m2"] is None
    assert data["units"] == []
