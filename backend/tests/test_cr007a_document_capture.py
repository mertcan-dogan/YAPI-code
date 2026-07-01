"""Track A: smart document capture (photo/PDF -> AI extract -> cost entry)."""
from app.constants import ROLE_DIRECTOR

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _file():
    return {"file": ("invoice.png", _PNG, "image/png")}


def test_capture_graceful_degradation_without_key(client, seed, monkeypatch):
    import app.services.ai as ai
    monkeypatch.setattr(ai, "is_available", lambda: False)
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/document-capture", files=_file())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AI_UNAVAILABLE"


def test_capture_rejects_bad_type(client, seed):
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/document-capture",
                    files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_capture_returns_extracted_fields(client, seed, monkeypatch):
    import app.services.ai as ai
    import app.api.document_capture as dc
    monkeypatch.setattr(ai, "is_available", lambda: True)
    monkeypatch.setattr(dc, "_upload_to_storage", lambda *a, **k: None)
    monkeypatch.setattr(ai, "analyze_document_image", lambda data, ct: {
        "supplier_name": "Beton A.Ş.", "invoice_number": "F-2025-1",
        "invoice_date": "2025-05-01", "amount_try": 150000, "vat_rate": 20,
        "description": "Hazır beton", "cost_category": "material_concrete", "confidence": 0.92,
    })
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/document-capture", files=_file())
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["extracted"]["supplier_name"] == "Beton A.Ş."
    assert data["document_path"]


def test_confirm_saves_cost_entry(client, seed):
    pid = _login(client, seed)
    cid = seed["a"]["company"].id
    body = {
        "document_path": f"{cid}/{pid}/abc.png",
        "entry_date": "2025-05-01",
        "cost_category": "material_concrete",
        "supplier_name": "Beton A.Ş.",
        "invoice_number": "F-2025-1",
        "amount_try": "150000",
        "vat_rate": "20",
        "payment_status": "unpaid",
    }
    r = client.post(f"/api/v1/projects/{pid}/document-capture/confirm", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["cost_category"] == "material_concrete"
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()
    assert costs["meta"]["total"] == 1
    # Document link stored with bucket prefix.
    assert costs["data"][0]["document_url"] == f"documents/{cid}/{pid}/abc.png"


def test_confirm_rejects_invalid_amount(client, seed):
    pid = _login(client, seed)
    body = {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "-5"}
    r = client.post(f"/api/v1/projects/{pid}/document-capture/confirm", json=body)
    assert r.status_code == 422
