"""CR-008-B — bulk layout reorder: atomic, rejects foreign ids (§3.2 / §11.1)."""
from app.constants import ROLE_DIRECTOR, ROLE_FINANCE

CHART = {
    "chart_type": "bar", "title": "t", "x_key": "k",
    "series": [{"key": "v", "label": "V", "type": "bar"}],
    "data": [{"k": "a", "v": 1}],
}


def _pin(client, title="x"):
    return client.post("/api/v1/workspace/items", json={"title": title, "item_type": "chart", "payload": CHART}).json()["data"]


def _layouts(client):
    return {i["id"]: i["layout"] for i in client.get("/api/v1/workspace/items").json()["data"]}


def test_bulk_layout_saves_all(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    a = _pin(client, "A")
    b = _pin(client, "B")
    r = client.put("/api/v1/workspace/layout", json={"items": [
        {"id": a["id"], "x": 0, "y": 0, "w": 6, "h": 4},
        {"id": b["id"], "x": 6, "y": 0, "w": 6, "h": 4},
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["updated"] == 2
    layouts = _layouts(client)
    assert layouts[a["id"]] == {"x": 0, "y": 0, "w": 6, "h": 4}
    assert layouts[b["id"]] == {"x": 6, "y": 0, "w": 6, "h": 4}


def test_bulk_layout_rejects_foreign_id_atomically(client, seed):
    # A owns one item; B owns another.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    a = _pin(client, "A-item")
    client.login(seed["a"]["users"][ROLE_FINANCE])
    b = _pin(client, "B-item")

    # A tries to save a batch that includes B's item id.
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put("/api/v1/workspace/layout", json={"items": [
        {"id": a["id"], "x": 1, "y": 1, "w": 2, "h": 2},
        {"id": b["id"], "x": 0, "y": 0, "w": 2, "h": 2},
    ]})
    assert r.status_code == 404
    # Atomic: A's own item layout was NOT written.
    assert _layouts(client)[a["id"]] is None


def test_bulk_layout_unknown_id_rejected(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    a = _pin(client)
    r = client.put("/api/v1/workspace/layout", json={"items": [
        {"id": a["id"], "x": 0, "y": 0, "w": 1, "h": 1},
        {"id": "99999999-9999-9999-9999-999999999999", "x": 0, "y": 0, "w": 1, "h": 1},
    ]})
    assert r.status_code == 404
    assert _layouts(client)[a["id"]] is None


def test_bulk_layout_empty_ok(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.put("/api/v1/workspace/layout", json={"items": []})
    assert r.status_code == 200
    assert r.json()["data"]["updated"] == 0


def test_bulk_layout_requires_auth(client):
    assert client.put("/api/v1/workspace/layout", json={"items": []}).status_code == 401
