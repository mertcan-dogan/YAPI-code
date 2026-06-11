"""CR-006-F: Excel içe aktarma — başlık tespiti, toplam satırı filtreleme, Türkçe hatalar."""
import io

from openpyxl import Workbook

from app.services.excel_import import (
    COLUMNS,
    ERR_AMOUNT_NUMERIC,
    ERR_DATE_ORDER,
    validate_rows,
)


def _xlsx(rows, header=COLUMNS):
    wb = Workbook()
    ws = wb.active
    if header is not None:
        ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(date="01.05.2025", category="Malzeme — Beton", amount="1000", due="", **extra):
    # 11 columns in template order.
    return [date, category, "", "", "", "", amount, "20", due, "Ödenmedi", ""]


# --- Header detection -------------------------------------------------------
def test_header_detected_by_keywords():
    data = _xlsx([_row()])  # COLUMNS header contains Tarih/Kategori/Tutar
    result = validate_rows(data)
    assert result["header_detected"] is True
    assert result["header_row"] == 1


def test_header_detected_by_numeric_ratio_fallback():
    # Header without keyword matches, but it is all text (numeric ratio 0 < %30).
    header = ["Belge", "Sınıf", "Detay", "Firma", "Not", "No", "Bedel", "KDV", "Vade", "Durum", "Ödeme"]
    data = _xlsx([_row()], header=header)
    result = validate_rows(data)
    assert result["header_detected"] is True
    assert result["header_row"] == 1


# --- Total / summary row filtering ------------------------------------------
def test_total_row_is_skipped():
    rows = [
        _row(amount="1000"),
        ["TOPLAM", "", "", "", "", "", "200000", "", "", "", ""],
    ]
    result = validate_rows(_xlsx(rows))
    total_rows = [r for r in result["rows"] if r["skipped"]]
    assert any("Toplam" in " ".join(r["errors"]) for r in total_rows)
    # The data row is still importable.
    assert any(r["valid"] and not r["skipped"] for r in result["rows"])


# --- Turkish error messages -------------------------------------------------
def test_unknown_category_message_lists_valid():
    result = validate_rows(_xlsx([_row(category="Uçan Halı")]))
    row = next(r for r in result["rows"] if not r["skipped"])
    msg = " ".join(row["errors"])
    assert "Kategori tanınmıyor: Uçan Halı" in msg
    assert "Geçerli kategoriler" in msg


def test_non_numeric_amount_message():
    result = validate_rows(_xlsx([_row(amount="100 TL")]))
    row = next(r for r in result["rows"] if not r["skipped"])
    assert ERR_AMOUNT_NUMERIC in row["errors"]


def test_due_before_invoice_date_message():
    # entry 10.05.2025, vade 01.05.2025 -> vade önce, hata.
    result = validate_rows(_xlsx([_row(date="10.05.2025", due="01.05.2025")]))
    row = next(r for r in result["rows"] if not r["skipped"])
    assert ERR_DATE_ORDER in row["errors"]


def test_valid_row_has_no_errors():
    result = validate_rows(_xlsx([_row(date="10.05.2025", due="31.05.2025")]))
    row = next(r for r in result["rows"] if not r["skipped"])
    assert row["valid"] is True and row["errors"] == []
