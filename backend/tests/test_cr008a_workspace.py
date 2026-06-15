"""CR-008-A — workspace_items CRUD: snapshot integrity, per-user isolation,
chart-payload validation reuse (CR-007-C), forged-id rejection (§11.1)."""
from app.constants import ROLE_DIRECTOR, ROLE_FINANCE

CHART = {
    "chart_type": "line",
    "title": "Akçansa Aylık",
    "x_key": "month",
    "series": [{"key": "total", "label": "Toplam", "type": "line"}],
    "data": [{"month": "2026-01", "total": 1000}, {"month": "2026-02", "total": 500}],
    "currency": "TRY",
    "source_note": "Kaynak: maliyet kayıtları",
}


def _A(seed):
    return seed["a"]["users"][ROLE_DIRECTOR]


def _B_same_company(seed):
    return seed["a"]["users"][ROLE_FINANCE]


# --------------------------------------------------------------------------- #
# Create + list + snapshot round-trip
# --------------------------------------------------------------------------- #
def test_create_chart_item_and_list(client, seed):
    client.login(_A(seed))
    r = client.post("/api/v1/workspace/items", json={"title": "Grafik", "item_type": "chart", "payload": CHART})
    assert r.status_code == 200, r.text
    item = r.json()["data"]
    assert item["item_type"] == "chart"
    # Snapshot round-trips through the CR-007-C validation (colours filled in).
    assert item["payload"]["chart_type"] == "line"
    assert item["payload"]["series"][0]["color"]
    assert len(item["payload"]["data"]) == 2

    r2 = client.get("/api/v1/workspace/items")
    assert r2.status_code == 200
    ids = [i["id"] for i in r2.json()["data"]]
    assert item["id"] in ids


def test_create_analysis_item(client, seed):
    client.login(_A(seed))
    payload = {"answer_markdown": "Akçansa ile **4.500 ₺** harcama.", "citations": [{"id": "1"}]}
    r = client.post("/api/v1/workspace/items", json={"title": "Analiz", "item_type": "analysis", "payload": payload})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["payload"]["answer_markdown"].startswith("Akçansa")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_chart_payload_validation_rejects_empty_data(client, seed):
    client.login(_A(seed))
    bad = {**CHART, "data": []}
    r = client.post("/api/v1/workspace/items", json={"title": "x", "item_type": "chart", "payload": bad})
    assert r.status_code == 422


def test_analysis_requires_answer_markdown(client, seed):
    client.login(_A(seed))
    r = client.post("/api/v1/workspace/items", json={"title": "x", "item_type": "analysis", "payload": {"citations": []}})
    assert r.status_code == 422


def test_invalid_item_type_rejected(client, seed):
    client.login(_A(seed))
    r = client.post("/api/v1/workspace/items", json={"title": "x", "item_type": "widget", "payload": {}})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Per-user isolation + forged ids
# --------------------------------------------------------------------------- #
def test_per_user_isolation(client, seed):
    client.login(_A(seed))
    item = client.post("/api/v1/workspace/items", json={"title": "Gizli", "item_type": "chart", "payload": CHART}).json()["data"]

    # Another user in the SAME company must not see or touch it.
    client.login(_B_same_company(seed))
    assert item["id"] not in [i["id"] for i in client.get("/api/v1/workspace/items").json()["data"]]
    assert client.put(f"/api/v1/workspace/items/{item['id']}", json={"title": "Hack"}).status_code == 404
    assert client.delete(f"/api/v1/workspace/items/{item['id']}").status_code == 404


def test_forged_company_id_in_body_ignored(client, seed):
    client.login(_A(seed))
    # Send a foreign company_id/user_id in the body — must be ignored; the item is
    # created under the authenticated user (company A).
    b_company = str(seed["b"]["company"].id)
    b_user = str(seed["b"]["users"][ROLE_DIRECTOR].id)
    r = client.post("/api/v1/workspace/items", json={
        "title": "x", "item_type": "chart", "payload": CHART,
        "company_id": b_company, "user_id": b_user,
    })
    assert r.status_code == 200, r.text
    item_id = r.json()["data"]["id"]

    # Company B's director cannot see it (it belongs to company A).
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert item_id not in [i["id"] for i in client.get("/api/v1/workspace/items").json()["data"]]


def test_cross_company_cannot_access(client, seed):
    client.login(_A(seed))
    item = client.post("/api/v1/workspace/items", json={"title": "A", "item_type": "chart", "payload": CHART}).json()["data"]
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.put(f"/api/v1/workspace/items/{item['id']}", json={"title": "z"}).status_code == 404


# --------------------------------------------------------------------------- #
# Update / delete / idempotency / auth
# --------------------------------------------------------------------------- #
def test_update_rename_and_layout(client, seed):
    client.login(_A(seed))
    item = client.post("/api/v1/workspace/items", json={"title": "Eski", "item_type": "chart", "payload": CHART}).json()["data"]
    r = client.put(f"/api/v1/workspace/items/{item['id']}", json={"title": "Yeni", "layout": {"x": 1, "y": 2, "w": 4, "h": 3}})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "Yeni"
    assert data["layout"] == {"x": 1, "y": 2, "w": 4, "h": 3}


def test_soft_delete_removes_from_list(client, seed):
    client.login(_A(seed))
    item = client.post("/api/v1/workspace/items", json={"title": "Sil", "item_type": "chart", "payload": CHART}).json()["data"]
    assert client.delete(f"/api/v1/workspace/items/{item['id']}").status_code == 200
    assert item["id"] not in [i["id"] for i in client.get("/api/v1/workspace/items").json()["data"]]


def test_idempotent_create_with_client_id(client, seed):
    client.login(_A(seed))
    cid = "11111111-1111-1111-1111-111111111111"
    body = {"id": cid, "title": "Bir", "item_type": "chart", "payload": CHART}
    r1 = client.post("/api/v1/workspace/items", json=body)
    r2 = client.post("/api/v1/workspace/items", json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"] == cid
    # Only one item exists.
    assert [i["id"] for i in client.get("/api/v1/workspace/items").json()["data"]].count(cid) == 1


def test_requires_auth(client):
    assert client.get("/api/v1/workspace/items").status_code == 401
    assert client.post("/api/v1/workspace/items", json={"title": "x", "item_type": "chart", "payload": CHART}).status_code == 401
