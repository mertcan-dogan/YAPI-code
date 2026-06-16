"""CR-010: equipment photo upload/delete (Supabase Storage public bucket).

Mirrors the company-logo path (test_cr006d_logo.py): magic-byte validation,
storage mocked via httpx, photo_urls persistence + audit.
"""
from sqlalchemy import select

from app.constants import ROLE_DIRECTOR
from app.models.audit_log import AuditLog

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff" + b"\x00" * 64


def _enable_storage(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "service-key")


class _Resp:
    status_code = 200
    text = ""


def _add_equipment(client, project_id):
    body = {
        "equipment_name": "Vinç", "ownership_type": "rented", "supplier_name": "Kiralama A.Ş.",
        "rate_try": "1000", "rate_unit": "day",
        "deployment_start": "2026-01-01", "deployment_end": "2026-01-20",
        "fuel_maintenance_try": "0", "add_to_budget": False,
    }
    r = client.post(f"/api/v1/projects/{project_id}/equipment", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


# --- Validation -------------------------------------------------------------
def test_photo_rejects_non_image(client, seed):
    a = seed["a"]
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 422


def test_photo_rejects_spoofed_content(client, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("x.png", b"not-a-png", "image/png")},
    )
    assert r.status_code == 422


def test_photo_rejects_oversize(client, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 10)
    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("big.png", big, "image/png")},
    )
    assert r.status_code == 422


def test_photo_404_for_missing_equipment(client, seed, monkeypatch):
    import uuid

    a = seed["a"]
    _enable_storage(monkeypatch)
    client.login(a["users"][ROLE_DIRECTOR])
    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{uuid.uuid4()}/photos",
        files={"file": ("logo.png", PNG, "image/png")},
    )
    assert r.status_code == 404


# --- Happy path -------------------------------------------------------------
def test_photo_upload_appends_url_and_audits(client, db, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    import app.api.equipment as equipment_api

    monkeypatch.setattr(equipment_api.httpx, "post", lambda *args, **kw: _Resp())
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)

    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("photo.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    urls = r.json()["data"]["photo_urls"]
    assert len(urls) == 1
    assert "/storage/v1/object/public/equipment-photos/" in urls[0]
    assert f"equipment_photos/{a['company'].id}/{eq_id}/" in urls[0]

    # A second upload appends rather than replaces.
    r2 = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("photo2.jpg", JPEG, "image/jpeg")},
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["data"]["photo_urls"]) == 2

    audits = db.execute(
        select(AuditLog).where(AuditLog.table_name == "equipment_log", AuditLog.action == "UPDATE")
    ).scalars().all()
    assert len(audits) == 2


def test_photo_persists_on_reload(client, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    import app.api.equipment as equipment_api

    monkeypatch.setattr(equipment_api.httpx, "post", lambda *args, **kw: _Resp())
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("photo.png", PNG, "image/png")},
    )
    # Re-fetching the list shows the persisted photo.
    rows = client.get(f"/api/v1/projects/{a['project'].id}/equipment").json()["data"]
    row = next(r for r in rows if r["id"] == eq_id)
    assert len(row["photo_urls"]) == 1


def test_photo_delete_removes_url(client, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    import app.api.equipment as equipment_api

    monkeypatch.setattr(equipment_api.httpx, "post", lambda *args, **kw: _Resp())
    monkeypatch.setattr(equipment_api.httpx, "request", lambda *args, **kw: _Resp())
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    up = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("photo.png", PNG, "image/png")},
    )
    url = up.json()["data"]["photo_urls"][0]

    r = client.request(
        "DELETE",
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        json={"url": url},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["photo_urls"] == []


def test_photo_delete_unknown_url_404(client, seed, monkeypatch):
    a = seed["a"]
    _enable_storage(monkeypatch)
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)
    r = client.request(
        "DELETE",
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        json={"url": "https://proj.supabase.co/x/nope.png"},
    )
    assert r.status_code == 404


def test_photo_company_isolation(client, seed, monkeypatch):
    """Company B cannot upload to company A's equipment."""
    a, b = seed["a"], seed["b"]
    _enable_storage(monkeypatch)
    client.login(a["users"][ROLE_DIRECTOR])
    eq_id = _add_equipment(client, a["project"].id)

    client.login(b["users"][ROLE_DIRECTOR])
    r = client.post(
        f"/api/v1/projects/{a['project'].id}/equipment/{eq_id}/photos",
        files={"file": ("logo.png", PNG, "image/png")},
    )
    assert r.status_code in (403, 404)
