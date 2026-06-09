"""CR-003-L: budget templates."""
from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])


def test_presets_listed(client, seed):
    _login(client, seed)
    data = client.get("/api/v1/budget-templates").json()["data"]
    names = {t["name"] for t in data}
    assert "Altyapı — Yol/Demiryolu" in names
    assert "Atıksu Arıtma" in names
    # Each preset distribution sums to 100.
    atiksu = next(t for t in data if t["name"] == "Atıksu Arıtma")
    assert sum(atiksu["distribution"].values()) == 100


def test_create_custom_template(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/budget-templates", json={"name": "Tünel", "distribution": {"labour_direct": 40, "material_concrete": 60}})
    assert r.status_code == 200, r.text
    data = client.get("/api/v1/budget-templates").json()["data"]
    assert any(t["name"] == "Tünel" and not t["is_preset"] for t in data)


def test_create_rejects_invalid_category(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/budget-templates", json={"name": "X", "distribution": {"bogus_cat": 100}})
    assert r.status_code == 422


def test_templates_company_scoped(client, seed):
    _login(client, seed)
    client.post("/api/v1/budget-templates", json={"name": "ŞirketA Şablonu", "distribution": {"labour_direct": 100}})
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    data = client.get("/api/v1/budget-templates").json()["data"]
    assert all(t["name"] != "ŞirketA Şablonu" for t in data)
