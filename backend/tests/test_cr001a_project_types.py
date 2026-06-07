"""CR-001-A: expanded project types + custom 'other' type."""
from app.constants import PROJECT_TYPES, ROLE_DIRECTOR


def _payload(**over):
    base = {
        "name": "Tip Testi",
        "project_code": "TIP-1",
        "project_type": "metro_tram",
        "client_name": "İşveren",
        "contract_value_try": "1000000",
        "original_budget_try": "800000",
        "start_date": "2025-01-01",
        "planned_end_date": "2025-12-31",
    }
    base.update(over)
    return base


def test_has_26_project_types():
    assert len(PROJECT_TYPES) == 26
    # A few of the new keys must be present.
    for key in ("motorway", "metro_tram", "dredging", "hospital", "urban_transformation"):
        assert key in PROJECT_TYPES


def test_create_with_new_type(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_payload(project_type="dredging"))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["project_type"] == "dredging"


def test_other_requires_custom_type(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/projects", json=_payload(project_type="other"))
    assert r.status_code == 422
    assert "proje türünü belirtin" in r.json()["error"]["message"].lower()


def test_other_with_custom_type_persists(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post(
        "/api/v1/projects",
        json=_payload(project_type="other", custom_project_type="Maden Tesisi"),
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["project_type"] == "other"
    assert data["custom_project_type"] == "Maden Tesisi"
