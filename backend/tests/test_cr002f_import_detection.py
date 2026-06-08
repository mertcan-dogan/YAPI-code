"""CR-002-F: header/total detection + sheet picker."""
import io

from openpyxl import Workbook

from app.constants import ROLE_DIRECTOR


def _login(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    return seed["a"]["project"].id


def _xlsx_with_header_and_total(sheets: dict[str, list[list]]):
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        for r in rows:
            ws.append(r)
        first = False
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Full 11-column template layout (positional parser).
HEADER = ["Tarih", "Kategori", "Alt Kategori", "Tedarikçi Adı", "Açıklama",
          "Fatura No", "Tutar TRY", "KDV Oranı", "Vade Tarihi", "Ödeme Durumu", "Ödeme Tarihi"]


def _data_row(d, cat, amount):
    return [d, cat, "", "", "", "", amount, "20", "", "Ödenmedi", ""]


def _file(data):
    return {"file": ("f.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def test_sheets_endpoint_lists_sheets(client, seed):
    pid = _login(client, seed)
    data = _xlsx_with_header_and_total({
        "Maliyet Girişleri": [HEADER],
        "Özet": [["x"]],
        "Bütçe Dağılımı": [["y"]],
    })
    r = client.post(f"/api/v1/projects/{pid}/costs/import/sheets", files=_file(data))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sheets"] == ["Maliyet Girişleri", "Özet", "Bütçe Dağılımı"]


def test_header_and_total_rows_skipped(client, seed):
    pid = _login(client, seed)
    rows = [
        ["Karadeniz Atıksu — Maliyet Listesi"],            # title row (no keywords)
        HEADER,                                            # header row
        _data_row("01.05.2025", "Malzeme — Beton", "150000"),
        _data_row("02.05.2025", "İşçilik — Direkt", "50000"),
        ["TOPLAM", "", "", "", "", "", "200000", "", "", "", ""],  # total row -> skipped
    ]
    data = _xlsx_with_header_and_total({"Maliyetler": rows})
    r = client.post(f"/api/v1/projects/{pid}/costs/import/preview", files=_file(data))
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["header_detected"] is True
    assert meta["valid"] == 2          # two data rows
    assert meta["skipped"] >= 1        # the TOPLAM row
    # No imported row should be the header/total.
    imported = [row for row in r.json()["data"] if not row["skipped"] and row["valid"]]
    assert len(imported) == 2


def test_preview_specific_sheet(client, seed):
    pid = _login(client, seed)
    data = _xlsx_with_header_and_total({
        "Özet": [["Bu sayfa boş özet"]],
        "Maliyet Girişleri": [HEADER, _data_row("01.05.2025", "Malzeme — Beton", "150000")],
    })
    r = client.post(
        f"/api/v1/projects/{pid}/costs/import/preview",
        files=_file(data),
        data={"sheet_name": "Maliyet Girişleri"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["valid"] == 1
