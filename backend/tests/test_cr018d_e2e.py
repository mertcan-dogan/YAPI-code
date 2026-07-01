"""CR-018-D: consolidated end-to-end pass over the cost-subcategory feature.

One flow exercising the whole feature together: a custom subcategory + a mix of
preset / custom / free-text / null cost entries, the (category, subcategory)
rollup with exact sums and the "Belirtilmemiş" bucket, the NULL-parent top-level
dedup guard, and company isolation. Per-aspect coverage lives in
test_cr018a_taxonomy.py and test_cr018b_subcategories.py. Dialect-safe (SQLite).
"""
from app.constants import ROLE_DIRECTOR

UNSPECIFIED = "Belirtilmemiş"


def _login(client, seed, co="a"):
    client.login(seed[co]["users"][ROLE_DIRECTOR])
    return seed[co]["project"].id


def _cost(client, pid, amount, subcategory=None, category="material_concrete"):
    body = {"entry_date": "2025-03-01", "cost_category": category,
            "amount_try": amount, "vat_rate": "20"}
    if subcategory is not None:
        body["subcategory"] = subcategory
    r = client.post(f"/api/v1/projects/{pid}/costs", json=body)
    assert r.status_code == 200, r.text
    return r


def test_subcategory_feature_end_to_end(client, seed):
    pid = _login(client, seed, "a")
    company_a = seed["a"]["company"].id

    # --- Custom subcategory under a standard category ---
    c = client.post("/api/v1/custom-categories", json={"name": "Beton Pompası", "parent_category": "material_concrete"})
    assert c.status_code == 200, c.text
    # It shows up (after presets) in the merged listing.
    items = client.get("/api/v1/cost-subcategories", params={"category": "material_concrete"}).json()["data"]
    assert {"key": "hazir_beton", "label": "Hazır Beton", "custom": False} in items
    assert any(i["label"] == "Beton Pompası" and i["custom"] for i in items)

    # --- A mix of cost entries on one project ---
    _cost(client, pid, "1000", subcategory="Hazır Beton")     # (a) preset      twv 1200
    _cost(client, pid, "250", subcategory="Hazır Beton")      # (a) preset again twv 300
    _cost(client, pid, "500", subcategory="Beton Pompası")    # (b) custom      twv 600
    _cost(client, pid, "300", subcategory="Özel Karışım")     # (c) free-text   twv 360
    _cost(client, pid, "200")                                  # (d) null/blank  twv 240

    # --- Rollup groups them correctly with exact Decimal sums ---
    data = client.get(f"/api/v1/projects/{pid}/costs/by-subcategory").json()["data"]["categories"]
    concrete = next(c for c in data if c["cost_category"] == "material_concrete")
    assert concrete["amount_try"] == "2250.00"          # 1000+250+500+300+200
    assert concrete["total_with_vat_try"] == "2700.00"  # 1200+300+600+360+240

    subs = {s["subcategory"]: s for s in concrete["subcategories"]}
    # Preset bucket sums the two Hazır Beton rows.
    assert subs["Hazır Beton"]["amount_try"] == "1250.00"
    assert subs["Hazır Beton"]["total_with_vat_try"] == "1500.00"
    # Custom subcategory is its own bucket.
    assert subs["Beton Pompası"]["amount_try"] == "500.00"
    assert subs["Beton Pompası"]["total_with_vat_try"] == "600.00"
    # Free-text "Diğer" value is its own bucket.
    assert subs["Özel Karışım"]["amount_try"] == "300.00"
    # Null/blank lands in the "Belirtilmemiş" bucket.
    assert subs[UNSPECIFIED]["amount_try"] == "200.00"
    assert subs[UNSPECIFIED]["total_with_vat_try"] == "240.00"

    # --- NULL-parent top-level dedup guard (still works in the same flow) ---
    a1 = client.post("/api/v1/custom-categories", json={"name": "Nakliye"}).json()["data"]
    a2 = client.post("/api/v1/custom-categories", json={"name": "nakliye"}).json()["data"]
    assert a1["id"] == a2["id"]              # deduped despite NULL parent
    assert a2["usage_count"] == 2
    assert a2["parent_category"] is None

    # --- Company isolation ---
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    # B sees presets only — none of A's custom subcategories.
    b_items = client.get("/api/v1/cost-subcategories", params={"category": "material_concrete"}).json()["data"]
    assert all(not i["custom"] for i in b_items)
    assert not any(i["label"] == "Beton Pompası" for i in b_items)
    # B cannot read A's rollup.
    assert client.get(f"/api/v1/projects/{pid}/costs/by-subcategory").status_code == 404
    # Sanity: the custom we created is genuinely A's.
    assert company_a == seed["a"]["company"].id
