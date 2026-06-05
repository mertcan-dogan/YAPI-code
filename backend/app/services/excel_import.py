"""Excel cost import — template, validation, preview (Section 9.1)."""
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
# Turkish label -> category key (case/space-insensitive match).
LABEL_TO_KEY = {label.lower(): key for key, label in COST_CATEGORIES.items()}


def build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Maliyetler"
    ws.append(COLUMNS)
    # Example row to guide the user.
    ws.append([
        "01.05.2025", "Malzeme — Beton", "C30 hazır beton", "Akçansa", "Saha dökümü",
        "FAT-2025-001", "150000", "20", "31.05.2025", "Ödenmedi", "",
    ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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


def validate_rows(file_bytes: bytes) -> list[dict]:
    """Return a preview list, each row tagged valid/invalid with errors."""
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows: list[dict] = []
    header_seen = False
    for idx, raw in enumerate(ws.iter_rows(min_row=1, values_only=True)):
        if not header_seen:
            header_seen = True
            continue  # skip header row
        if raw is None or all(c in (None, "") for c in raw):
            continue
        cells = list(raw) + [None] * (len(COLUMNS) - len(raw))
        errors: list[str] = []
        parsed: dict = {}

        # Tarih (required)
        try:
            d = _parse_date(cells[0])
            if d is None:
                errors.append("Tarih zorunludur")
            elif d < MIN_DATE or d > max_future_date(1):
                errors.append("Geçersiz tarih")
            else:
                parsed["entry_date"] = d
        except ValueError as e:
            errors.append(str(e))

        # Kategori (required, must match)
        cat_label = (str(cells[1]).strip().lower() if cells[1] else "")
        key = LABEL_TO_KEY.get(cat_label)
        if not key:
            errors.append("Bilinmeyen kategori")
        else:
            parsed["cost_category"] = key

        parsed["subcategory"] = str(cells[2]).strip() if cells[2] else None
        parsed["supplier_name"] = str(cells[3]).strip() if cells[3] else None
        parsed["description"] = str(cells[4]).strip() if cells[4] else None
        parsed["invoice_number"] = str(cells[5]).strip() if cells[5] else None

        # Tutar (required)
        try:
            parsed["amount_try"] = _parse_amount(cells[6])
        except ValueError as e:
            errors.append(str(e))

        # KDV (default 20)
        try:
            parsed["vat_rate"] = Decimal(str(cells[7])) if cells[7] not in (None, "") else Decimal("20")
        except (InvalidOperation, ValueError):
            errors.append("Geçersiz KDV oranı")

        # Vade
        try:
            parsed["payment_due_date"] = _parse_date(cells[8])
        except ValueError:
            errors.append("Geçersiz vade tarihi")

        # Ödeme durumu
        status_raw = (str(cells[9]).strip().lower() if cells[9] else "ödenmedi")
        parsed["payment_status"] = "paid" if status_raw in ("ödendi", "odendi", "paid") else "unpaid"

        # Ödeme tarihi (required if paid)
        try:
            parsed["date_paid"] = _parse_date(cells[10])
        except ValueError:
            errors.append("Geçersiz ödeme tarihi")
        if parsed["payment_status"] == "paid" and not parsed.get("date_paid"):
            errors.append("Ödendi durumunda ödeme tarihi zorunludur")

        rows.append({"row": idx + 1, "valid": not errors, "errors": errors, "data": parsed})

    return rows
