"""CR-002-I: security layers — headers, lockout, XSS, MIME, encryption."""
import io

from openpyxl import Workbook

from app.constants import ROLE_DIRECTOR


# --- 10.6 Security headers ---
def test_security_headers_present(client):
    r = client.get("/health")
    h = r.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert "max-age=31536000" in h.get("Strict-Transport-Security", "")
    assert h.get("Content-Security-Policy") == "default-src 'self'"
    assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# --- 10.2 Login lockout ---
def test_login_lockout_after_5_failures(client, seed, monkeypatch):
    # Configure Supabase so /login proceeds to the credential check, and make the
    # upstream call always fail credentials.
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon")

    class FakeResp:
        status_code = 401

        def json(self):
            return {}

    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod.httpx, "post", lambda *a, **k: FakeResp())

    body = {"email": "x@example.com", "password": "wrong"}
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json=body)
        assert r.status_code == 401
    # 6th attempt is locked out.
    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "ACCOUNT_LOCKED"


# --- 10.5 XSS sanitisation ---
def test_xss_payload_sanitised_on_cost_entry(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    r = client.post(
        f"/api/v1/projects/{pid}/costs",
        json={"entry_date": "2025-03-01", "cost_category": "other", "amount_try": "1000",
              "description": "<script>alert('x')</script>Beton dökümü",
              "supplier_name": "<b>Akçansa</b>"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "<script>" not in data["description"]
    assert "Beton dökümü" in data["description"]
    assert "<b>" not in data["supplier_name"]
    assert "Akçansa" in data["supplier_name"]


# --- 10.5 MIME validation ---
def test_upload_rejects_spoofed_content(client, seed, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "svc")
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    # Declares PDF but the bytes are not a PDF -> rejected before any upload.
    r = client.post(
        "/api/v1/upload/document",
        files={"file": ("evil.pdf", b"<html>not a pdf</html>", "application/pdf")},
    )
    assert r.status_code == 422
    assert "uyuşmuyor" in r.json()["error"]["message"]


# --- 10.2 Per-user import limit ---
def test_import_rate_limit(client, seed, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "import_rate_per_minute", 3)
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    wb = Workbook(); wb.active.append(["Tarih", "Kategori", "Tutar TRY"]); buf = io.BytesIO(); wb.save(buf)
    f = {"file": ("f.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    codes = [client.post(f"/api/v1/projects/{pid}/costs/import/preview", files=f).status_code for _ in range(4)]
    assert codes.count(429) >= 1


# --- 10.3 Field encryption round-trip ---
def test_encryption_round_trip(monkeypatch):
    from app.config import settings
    from app.utils import crypto

    monkeypatch.setattr(settings, "encryption_key", "test-secret-passphrase")
    token = crypto.encrypt("Gizli sözleşme detayı")
    assert token != "Gizli sözleşme detayı"
    assert crypto.decrypt(token) == "Gizli sözleşme detayı"
