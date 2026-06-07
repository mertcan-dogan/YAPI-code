"""CR-001-F: Excel import preview + all-or-nothing confirm."""
import io

from openpyxl import Workbook

from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append([
        "Tarih", "Kategori", "Alt Kategori", "Tedarikçi Adı", "Açıklama",
        "Fatura No", "Tutar TRY", "KDV Oranı", "Vade Tarihi", "Ödeme Durumu", "Ödeme Tarihi",
    ])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_preview_does_not_save(client, seed):
    pid = _login(client, seed)
    data = _xlsx([["01.05.2025", "Malzeme — Beton", "", "Akçansa", "", "", "150000", "20", "", "Ödenmedi", ""]])
    r = client.post(
        f"/api/v1/projects/{pid}/costs/import/preview",
        files={"file": ("f.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] == 1
    assert body["meta"]["valid"] == 1
    # Nothing persisted by preview.
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"]
    assert costs == 0


def test_preview_flags_invalid_rows(client, seed):
    pid = _login(client, seed)
    data = _xlsx([["GEÇERSİZ", "Bilinmeyen Kategori", "", "", "", "", "-5", "20", "", "Ödenmedi", ""]])
    r = client.post(
        f"/api/v1/projects/{pid}/costs/import/preview",
        files={"file": ("f.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    body = r.json()
    assert body["meta"]["invalid"] == 1
    assert body["data"][0]["valid"] is False
    assert len(body["data"][0]["errors"]) > 0


def test_confirm_bulk_saves_edited_rows(client, seed):
    pid = _login(client, seed)
    rows = [
        {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "150000", "vat_rate": "20"},
        {"entry_date": "2025-05-02", "cost_category": "labour_direct", "amount_try": "50000", "vat_rate": "20"},
    ]
    r = client.post(f"/api/v1/projects/{pid}/costs/import/confirm", json={"rows": rows})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["imported"] == 2
    assert client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"] == 2


def test_confirm_is_all_or_nothing(client, seed):
    pid = _login(client, seed)
    rows = [
        {"entry_date": "2025-05-01", "cost_category": "material_concrete", "amount_try": "150000", "vat_rate": "20"},
        {"entry_date": "2025-05-02", "cost_category": "labour_direct", "amount_try": "-1", "vat_rate": "20"},  # invalid
    ]
    r = client.post(f"/api/v1/projects/{pid}/costs/import/confirm", json={"rows": rows})
    assert r.status_code == 422
    # Nothing saved because one row was invalid.
    assert client.get(f"/api/v1/projects/{pid}/costs").json()["meta"]["total"] == 0


def test_template_download_authenticated(client, seed):
    pid = _login(client, seed)
    r = client.get(f"/api/v1/projects/{pid}/costs/import/template")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
