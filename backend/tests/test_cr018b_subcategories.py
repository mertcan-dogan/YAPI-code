"""CR-018-B: subcategory listing API, custom-subcategory create/dedup, and the
(category, subcategory) cost rollup. SQLite-backed via the portable types.
"""
from decimal import Decimal

from app.constants import ROLE_DIRECTOR


def _login(client, seed, co="a", role=ROLE_DIRECTOR):
    client.login(seed[co]["users"][role])
    return seed[co]["project"].id


def _cost(client, pid, **over):
    body = {"entry_date": "2025-03-01", "cost_category": "material_concrete",
            "amount_try": "1000", "vat_rate": "20"}
    body.update(over)
    return client.post(f"/api/v1/projects/{pid}/costs", json=body)


# --------------------------------------------------------------------------- #
# GET /cost-subcategories
# --------------------------------------------------------------------------- #
def test_list_presets_for_category(client, seed):
    _login(client, seed)
    r = client.get("/api/v1/cost-subcategories", params={"category": "labour_direct"})
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    keys = [i["key"] for i in items]
    assert "elektrik" in keys and "sihhi_tesisat" in keys
    assert all(i["custom"] is False for i in items)  # presets only, no customs yet


def test_invalid_category_rejected(client, seed):
    _login(client, seed)
    r = client.get("/api/v1/cost-subcategories", params={"category": "nope"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_CATEGORY"


def test_custom_subcategory_appears_after_presets(client, seed):
    _login(client, seed)
    c = client.post("/api/v1/custom-categories", json={"name": "Asma Tavan", "parent_category": "labour_direct"})
    assert c.status_code == 200, c.text
    assert c.json()["data"]["parent_category"] == "labour_direct"
    items = client.get("/api/v1/cost-subcategories", params={"category": "labour_direct"}).json()["data"]
    customs = [i for i in items if i["custom"]]
    assert [i["label"] for i in customs] == ["Asma Tavan"]
    # presets still present and ordered before customs
    assert items[0]["custom"] is False
    assert items[-1]["label"] == "Asma Tavan"


# --------------------------------------------------------------------------- #
# Custom subcategory create + dedup
# --------------------------------------------------------------------------- #
def test_custom_subcategory_dedup_by_parent_and_name(client, seed):
    _login(client, seed)
    a = client.post("/api/v1/custom-categories", json={"name": "Köpük", "parent_category": "material_other"}).json()["data"]
    b = client.post("/api/v1/custom-categories", json={"name": "köpük", "parent_category": "material_other"}).json()["data"]
    assert a["id"] == b["id"]                # deduped, same row
    assert b["usage_count"] == 2             # usage bumped for ordering


def test_same_subname_under_different_parents_distinct(client, seed):
    _login(client, seed)
    a = client.post("/api/v1/custom-categories", json={"name": "Özel", "parent_category": "labour_direct"}).json()["data"]
    b = client.post("/api/v1/custom-categories", json={"name": "Özel", "parent_category": "material_other"}).json()["data"]
    assert a["id"] != b["id"]                # different parents -> distinct rows


def test_invalid_parent_category_rejected(client, seed):
    _login(client, seed)
    r = client.post("/api/v1/custom-categories", json={"name": "X", "parent_category": "not_a_category"})
    assert r.status_code == 422


def test_top_level_dedup_still_works_null_parent(client, seed):
    """Regression guard: the new unique constraint can't dedup NULL-parent rows
    (SQL NULLs are distinct), so app-code must still dedup top-level customs."""
    _login(client, seed)
    a = client.post("/api/v1/custom-categories", json={"name": "Nakliye"}).json()["data"]
    b = client.post("/api/v1/custom-categories", json={"name": "nakliye"}).json()["data"]
    assert a["id"] == b["id"]
    assert b["usage_count"] == 2
    assert b["parent_category"] is None
    # And only one top-level row exists with that name.
    tops = [c for c in client.get("/api/v1/custom-categories").json()["data"] if c["name"] == "Nakliye"]
    assert len(tops) == 1


# --------------------------------------------------------------------------- #
# Cost subcategory persistence (controlled value + legacy free-text)
# --------------------------------------------------------------------------- #
def test_cost_persists_controlled_subcategory(client, seed):
    pid = _login(client, seed)
    cid = _cost(client, pid, subcategory="Hazır Beton").json()["data"]["id"]
    row = client.get(f"/api/v1/projects/{pid}/costs").json()["data"]
    assert next(c for c in row if c["id"] == cid)["subcategory"] == "Hazır Beton"


def test_cost_accepts_legacy_freetext_subcategory(client, seed):
    pid = _login(client, seed)
    r = _cost(client, pid, subcategory="eski serbest metin")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["subcategory"] == "eski serbest metin"


# --------------------------------------------------------------------------- #
# Rollup by (category, subcategory)
# --------------------------------------------------------------------------- #
def test_rollup_exact_with_unspecified_bucket(client, seed):
    pid = _login(client, seed)
    _cost(client, pid, subcategory="Hazır Beton", amount_try="1000")  # twv 1200
    _cost(client, pid, subcategory="Hazır Beton", amount_try="500")   # twv 600
    _cost(client, pid, subcategory="Çimento", amount_try="300")       # twv 360
    _cost(client, pid, amount_try="200")                              # no subcat -> Belirtilmemiş, twv 240

    data = client.get(f"/api/v1/projects/{pid}/costs/by-subcategory").json()["data"]["categories"]
    concrete = next(c for c in data if c["cost_category"] == "material_concrete")
    assert concrete["amount_try"] == "2000.00"
    assert concrete["total_with_vat_try"] == "2400.00"

    subs = {s["subcategory"]: s for s in concrete["subcategories"]}
    assert subs["Hazır Beton"]["amount_try"] == "1500.00"
    assert subs["Hazır Beton"]["total_with_vat_try"] == "1800.00"
    assert subs["Çimento"]["amount_try"] == "300.00"
    assert subs["Belirtilmemiş"]["amount_try"] == "200.00"
    assert subs["Belirtilmemiş"]["total_with_vat_try"] == "240.00"


def test_rollup_legacy_blank_rolls_into_unspecified(client, seed):
    pid = _login(client, seed)
    _cost(client, pid, cost_category="labour_direct", amount_try="100")  # null subcat
    data = client.get(f"/api/v1/projects/{pid}/costs/by-subcategory").json()["data"]["categories"]
    labour = next(c for c in data if c["cost_category"] == "labour_direct")
    assert [s["subcategory"] for s in labour["subcategories"]] == ["Belirtilmemiş"]
    assert labour["subcategories"][0]["amount_try"] == "100.00"


# --------------------------------------------------------------------------- #
# Company isolation
# --------------------------------------------------------------------------- #
def test_company_b_does_not_see_company_a_custom_subcategories(client, seed):
    _login(client, seed, "a")
    client.post("/api/v1/custom-categories", json={"name": "Gizli", "parent_category": "labour_direct"})

    _login(client, seed, "b")
    items = client.get("/api/v1/cost-subcategories", params={"category": "labour_direct"}).json()["data"]
    assert all(not i["custom"] for i in items)  # B sees presets only, none of A's customs


def test_rollup_cross_company_404(client, seed):
    _login(client, seed, "a")
    a_pid = seed["a"]["project"].id
    _login(client, seed, "b")
    r = client.get(f"/api/v1/projects/{a_pid}/costs/by-subcategory")
    assert r.status_code == 404
