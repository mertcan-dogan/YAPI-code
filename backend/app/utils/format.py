"""Turkish number, currency and date formatting (Section 14.1).

Turkish format: thousands separator '.', decimal separator ','.
Example: 1.234.567,89 ₺
"""
from datetime import date, datetime
from decimal import Decimal


def format_number_tr(value, decimals: int = 2) -> str:
    if value is None:
        value = 0
    d = Decimal(str(value)).quantize(Decimal(10) ** -decimals)
    sign = "-" if d < 0 else ""
    d = abs(d)
    int_part, _, frac_part = f"{d:.{decimals}f}".partition(".")
    # Group integer part with '.' every 3 digits.
    grouped = ""
    while len(int_part) > 3:
        grouped = "." + int_part[-3:] + grouped
        int_part = int_part[:-3]
    grouped = int_part + grouped
    if decimals > 0:
        return f"{sign}{grouped},{frac_part}"
    return f"{sign}{grouped}"


def format_currency_tr(value, symbol: str = "₺") -> str:
    return f"{format_number_tr(value, 2)} {symbol}"


def format_pct_tr(value) -> str:
    return f"%{format_number_tr(value, 1)}"


def format_date_tr(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d.%m.%Y")


def format_datetime_tr(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    return d.strftime("%d.%m.%Y %H:%M")
