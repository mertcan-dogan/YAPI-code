"""AI Asistan conversation history — per-user, cross-device sync."""
import uuid

from app.constants import ROLE_DIRECTOR, ROLE_FINANCE


def _put(client, conv_id, **kw):
    body = {"title": kw.get("title", "Test sohbet"), "messages": kw.get("messages", []), "project_id": kw.get("project_id")}
    return client.put(f"/api/v1/ai/conversations/{conv_id}", json=body)


# --- Empty state ------------------------------------------------------------
def test_list_empty(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.get("/api/v1/ai/conversations")
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


# --- Create via upsert ------------------------------------------------------
def test_upsert_creates(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    msgs = [{"role": "user", "text": "Merhaba"}, {"role": "ai", "text": "Selam", "at": "2026-06-15T10:00:00+00:00"}]
    r = _put(client, cid, title="İlk sohbet", messages=msgs)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["id"] == cid
    assert data["title"] == "İlk sohbet"
    assert len(data["messages"]) == 2
    assert data["messages"][1]["text"] == "Selam"

    listed = client.get("/api/v1/ai/conversations").json()["data"]
    assert len(listed) == 1 and listed[0]["id"] == cid


# --- Update appends / overwrites in place -----------------------------------
def test_upsert_updates_same_id(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    _put(client, cid, title="t", messages=[{"role": "user", "text": "1"}])
    _put(client, cid, title="t", messages=[{"role": "user", "text": "1"}, {"role": "ai", "text": "2"}])
    listed = client.get("/api/v1/ai/conversations").json()["data"]
    assert len(listed) == 1  # still one row
    assert len(listed[0]["messages"]) == 2


# --- Delete (soft) ----------------------------------------------------------
def test_delete(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    _put(client, cid, title="silinecek")
    r = client.delete(f"/api/v1/ai/conversations/{cid}")
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/ai/conversations").json()["data"] == []


def test_delete_missing_404(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.delete(f"/api/v1/ai/conversations/{uuid.uuid4()}")
    assert r.status_code == 404


# --- Isolation: private to the owning user ----------------------------------
def test_private_to_user(client, seed):
    director = seed["a"]["users"][ROLE_DIRECTOR]
    finance = seed["a"]["users"][ROLE_FINANCE]
    client.login(director)
    cid = str(uuid.uuid4())
    _put(client, cid, title="yöneticinin sohbeti")
    # Same company, different user — must not see it.
    client.login(finance)
    assert client.get("/api/v1/ai/conversations").json()["data"] == []
    # ...and cannot delete it.
    assert client.delete(f"/api/v1/ai/conversations/{cid}").status_code == 404


# --- Isolation: across companies --------------------------------------------
def test_isolation_across_companies(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    _put(client, cid, title="A şirketi sohbeti")
    client.login(seed["b"]["users"][ROLE_DIRECTOR])
    assert client.get("/api/v1/ai/conversations").json()["data"] == []


# --- Validation -------------------------------------------------------------
def test_rejects_bad_role(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    cid = str(uuid.uuid4())
    r = _put(client, cid, title="t", messages=[{"role": "system", "text": "x"}])
    assert r.status_code == 422


def test_requires_auth(client, seed):
    cid = str(uuid.uuid4())
    assert _put(client, cid).status_code == 401
    assert client.get("/api/v1/ai/conversations").status_code == 401
