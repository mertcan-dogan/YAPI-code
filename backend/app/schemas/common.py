"""Shared schema primitives and validation constants (Section 9.3)."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

MIN_DATE = date(1990, 1, 1)


def max_future_date(years: int = 1) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year + years)
    except ValueError:  # Feb 29
        return today.replace(year=today.year + years, day=28)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Turkish validation error messages (Section 9.3)
ERR_AMOUNT = "Tutar 0'dan büyük olmalıdır"
ERR_DATE = "Geçersiz tarih"
ERR_INVOICE_DUP = "Bu fatura numarası zaten mevcut"
ERR_DUE_BEFORE_ENTRY = "Vade tarihi fatura tarihinden önce olamaz"
ERR_CONTRACT = "Sözleşme değeri 0'dan büyük olmalıdır"
ERR_RETENTION = "Kesinti oranı 0-50 arasında olmalıdır"
ERR_EMAIL = "Geçerli bir e-posta adresi girin"


def positive_amount(v: Decimal) -> Decimal:
    if v is None or v <= 0:
        raise ValueError(ERR_AMOUNT)
    return v


def valid_entry_date(v: date) -> date:
    if v < MIN_DATE or v > max_future_date(1):
        raise ValueError(ERR_DATE)
    return v
