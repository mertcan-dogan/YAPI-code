"""CR-002-H: AI Excel auto-import."""
import io

from openpyxl import Workbook

from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["Tarih", "Açıklama", "Tutar"])
    ws.append(["2025-05-01", "Beton", "150000"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _file(data):
    return {"file": ("f.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def test_ai_import_graceful_degradation_without_key(client, seed, monkeypatch):
    # No ANTHROPIC_API_KEY -> AI unavailable -> 503 with standard-import message.
    import app.services.ai as ai

    monkeypatch.setattr(ai, "is_available", lambda: False)
    pid = _login(client, seed)
    r = client.post(f"/api/v1/projects/{pid}/ai-import", files=_file(_xlsx()))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AI_UNAVAILABLE"


def test_ai_import_confirm_saves_records(client, seed):
    # confirm accepts already-structured data (AI step bypassed) and persists it.
    pid = _login(client, seed)
    body = {
        "maliyet_girisleri": [
            {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "150000", "vat_rate": "20", "confidence": 0.95},
            {"entry_date": "2025-05-02", "cost_category": "Malzeme — Çelik/Demir", "amount_try": "80000", "vat_rate": "20", "confidence": 0.7},
        ],
        "alt_yukleniciler": [
            {"name": "Kazı A.Ş.", "contract_value_try": "500000", "confidence": 0.9},
        ],
        "faturalar": [],
        "ekipman": [],
    }
    r = client.post(f"/api/v1/projects/{pid}/ai-import/confirm", json=body)
    assert r.status_code == 200, r.text
    imported = r.json()["data"]["imported"]
    assert imported["maliyet_girisleri"] == 2  # Turkish label normalised to a key
    assert imported["alt_yukleniciler"] == 1
    # Cost entries actually persisted.
    assert client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"] == 2


def test_ai_import_confirm_skips_invalid(client, seed):
    pid = _login(client, seed)
    body = {"maliyet_girisleri": [{"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "-5", "confidence": 0.9}]}
    r = client.post(f"/api/v1/projects/{pid}/ai-import/confirm", json=body)
    assert r.status_code == 200
    assert r.json()["data"]["imported"]["maliyet_girisleri"] == 0
    assert r.json()["data"]["skipped"] == 1
