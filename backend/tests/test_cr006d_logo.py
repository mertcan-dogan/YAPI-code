"""CR-006-D: şirket logosu yükleme (Supabase Storage) + sidebar/PDF entegrasyonu."""
from app.constants import ROLE_DIRECTOR, ROLE_SITE_MANAGER

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff" + b"\x00" * 64


def _enable_storage(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "service-key")


class _Resp:
    status_code = 200


# --- Validation -------------------------------------------------------------
def test_logo_rejects_non_image(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/settings/company/logo",
                    files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 422


def test_logo_rejects_oversize(client, seed, monkeypatch):
    _enable_storage(monkeypatch)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024 + 10)
    r = client.post("/api/v1/settings/company/logo",
                    files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 422


def test_logo_rejects_spoofed_content(client, seed, monkeypatch):
    _enable_storage(monkeypatch)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/settings/company/logo",
                    files={"file": ("x.png", b"not-a-png", "image/png")})
    assert r.status_code == 422


def test_logo_requires_director(client, seed):
    client.login(seed["a"]["users"][ROLE_SITE_MANAGER])
    r = client.post("/api/v1/settings/company/logo",
                    files={"file": ("logo.png", PNG, "image/png")})
    assert r.status_code == 403


# --- Happy path -------------------------------------------------------------
def test_logo_upload_sets_url(client, seed, monkeypatch):
    _enable_storage(monkeypatch)
    import app.api.settings as settings_api

    monkeypatch.setattr(settings_api.httpx, "post", lambda *a, **k: _Resp())
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.post("/api/v1/settings/company/logo",
                    files={"file": ("logo.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["data"]["logo_url"]
    assert "/storage/v1/object/public/company-logos/" in url
    assert url.endswith(f"company_logos/{seed['a']['company'].id}/logo.png")


def test_logo_delete_clears_url(client, db, seed, monkeypatch):
    seed["a"]["company"].logo_url = "https://proj.supabase.co/x/logo.png"
    db.commit()
    _enable_storage(monkeypatch)
    import app.api.settings as settings_api

    monkeypatch.setattr(settings_api.httpx, "request", lambda *a, **k: _Resp())
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    r = client.delete("/api/v1/settings/company/logo")
    assert r.status_code == 200
    assert r.json()["data"]["logo_url"] is None


# --- /auth/me exposes company branding --------------------------------------
def test_me_includes_company_logo(client, db, seed):
    seed["a"]["company"].logo_url = "https://cdn/logo.png"
    db.commit()
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    data = client.get("/api/v1/auth/me").json()["data"]
    assert data["company_logo_url"] == "https://cdn/logo.png"
    assert data["company_name"] == seed["a"]["company"].name


# --- PDF logo loader is failure-tolerant ------------------------------------
def test_logo_flowable_handles_bad_url():
    from app.services.reports import _logo_flowable

    assert _logo_flowable(None) is None
    assert _logo_flowable("https://nonexistent.invalid/logo.png") is None
