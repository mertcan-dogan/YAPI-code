"""Excel cost import — template, sheet listing, validation (Section 9.1 + CR-002-F)."""
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook

from app.constants import COST_CATEGORIES
from app.schemas.common import MIN_DATE, max_future_date

# Template columns in order (Section 9.1).
COLUMNS = [
    "Tarih", "Kategori", "Alt Kategori", "Tedarikçi Adı", "Açıklama",
    "Fatura No", "Tutar TRY", "KDV Oranı", "Vade Tarihi", "Ödeme Durumu", "Ödeme Tarihi",
]
LABEL_TO_KEY = {label.lower(): key for key, label in COST_CATEGORIES.items()}

# CR-002-F detection keywords.
HEADER_KEYWORDS = {"tarih", "kategori", "tutar"}
TOTAL_KEYWORDS = ("toplam", "total", "sum", "genel")


def build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Maliyetler"
    ws.append(COLUMNS)
    ws.append([
        "01.05.2025", "Malzeme — Beton", "C30 hazır beton", "Akçansa", "Saha dökümü",
        "FAT-2025-001", "150000", "20", "31.05.2025", "Ödenmedi", "",
    ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def list_sheet_names(file_bytes: bytes) -> list[str]:
    """CR-002-F: return the sheet names of an uploaded workbook."""
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    return list(wb.sheetnames)


MAX_AI_ROWS = 500


def excel_to_text(file_bytes: bytes) -> tuple[str, bool, int]:
    """CR-002-H: flatten every sheet to text for the AI analyser.

    Returns (text, truncated, row_count). At most MAX_AI_ROWS data rows across all
    sheets; formula cells are read as their resolved values (data_only=True).
    """
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    lines: list[str] = []
    count = 0
    truncated = False
    for name in wb.sheetnames:
        ws = wb[name]
        lines.append(f"### SAYFA: {name}")
        for row in ws.iter_rows(values_only=True):
            if count >= MAX_AI_ROWS:
                truncated = True
                break
            cells = ["" if c is None else str(c) for c in row]
            if not any(cells):
                continue
            lines.append(" | ".join(cells))
            count += 1
        if truncated:
            break
    return "\n".join(lines), truncated, count


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("Geçersiz tarih")


def _parse_amount(value) -> Decimal:
    if value in (None, ""):
        raise ValueError("Tutar zorunludur")
    s = str(value).replace(".", "").replace(",", ".") if isinstance(value, str) else value
    try:
        d = Decimal(str(s))
    except (InvalidOperation, ValueError):
        raise ValueError("Geçersiz tutar")
    if d <= 0:
        raise ValueError("Tutar 0'dan büyük olmalıdır")
    return d


def _looks_like_header(cells: list) -> int:
    """Count how many header keywords appear in a row's cells."""
    text = " ".join(str(c).lower() for c in cells if c not in (None, ""))
    return sum(1 for kw in HEADER_KEYWORDS if kw in text)


def _is_total_row(cells: list) -> bool:
    text = " ".join(str(c).lower() for c in cells if c not in (None, ""))
    return any(kw in text for kw in TOTAL_KEYWORDS)


def validate_rows(file_bytes: bytes, sheet_name: str | None = None) -> dict:
    """Parse + validate a sheet (CR-002-F).

    Returns {header_detected, header_row, rows: [...]}. Each row dict has:
      row, valid, skipped, errors, data. Header and total/summary/empty-date rows
      are flagged 'skipped' (shown grey) rather than imported.
    """
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    raw = [list(r) for r in ws.iter_rows(values_only=True)]

    # --- Header detection: scan first 5 rows for >=2 header keywords. ---
    header_row = None
    for i, cells in enumerate(raw[:5]):
        if _looks_like_header(cells) >= 2:
            header_row = i
            break
    header_detected = header_row is not None
    if header_row is None:
        header_row = 0  # assume the first row is the header

    rows: list[dict] = []
    for idx in range(header_row + 1, len(raw)):
        cells = list(raw[idx]) + [None] * (len(COLUMNS) - len(raw[idx]))
        if all(c in (None, "") for c in cells[: len(COLUMNS)]):
            continue  # blank line

        # CR-002-F: skip total/summary rows.
        if _is_total_row(cells):
            rows.append({"row": idx + 1, "valid": False, "skipped": True,
                         "errors": ["Bu satır otomatik olarak atlandı: Toplam satırı"], "data": {}})
            continue

        errors: list[str] = []
        parsed: dict = {}

        # Tarih — empty/invalid means this is not a data row -> skip (grey).
        try:
            d = _parse_date(cells[0])
        except ValueError:
            d = None
        if d is None:
            rows.append({"row": idx + 1, "valid": False, "skipped": True,
                         "errors": ["Bu satır otomatik olarak atlandı: Tarih boş/geçersiz"], "data": {}})
            continue
        if d < MIN_DATE or d > max_future_date(1):
            errors.append("Geçersiz tarih")
        else:
            parsed["entry_date"] = d

        cat_label = (str(cells[1]).strip().lower() if cells[1] else "")
        key = LABEL_TO_KEY.get(cat_label)
        if not key:
            errors.append("Kategori tanınmıyor")
        else:
            parsed["cost_category"] = key

        parsed["subcategory"] = str(cells[2]).strip() if cells[2] else None
        parsed["supplier_name"] = str(cells[3]).strip() if cells[3] else None
        parsed["description"] = str(cells[4]).strip() if cells[4] else None
        parsed["invoice_number"] = str(cells[5]).strip() if cells[5] else None

        try:
            parsed["amount_try"] = _parse_amount(cells[6])
        except ValueError as e:
            errors.append(str(e))

        try:
            parsed["vat_rate"] = Decimal(str(cells[7])) if cells[7] not in (None, "") else Decimal("20")
        except (InvalidOperation, ValueError):
            errors.append("Geçersiz KDV oranı")

        try:
            parsed["payment_due_date"] = _parse_date(cells[8])
        except ValueError:
            errors.append("Geçersiz vade tarihi")

        status_raw = (str(cells[9]).strip().lower() if cells[9] else "ödenmedi")
        parsed["payment_status"] = "paid" if status_raw in ("ödendi", "odendi", "paid") else "unpaid"

        try:
            parsed["date_paid"] = _parse_date(cells[10])
        except ValueError:
            errors.append("Geçersiz ödeme tarihi")
        if parsed["payment_status"] == "paid" and not parsed.get("date_paid"):
            errors.append("Ödendi durumunda ödeme tarihi zorunludur")

        rows.append({"row": idx + 1, "valid": not errors, "skipped": False, "errors": errors, "data": parsed})

    return {"header_detected": header_detected, "header_row": header_row + 1, "rows": rows}
