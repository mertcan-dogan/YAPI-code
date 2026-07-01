"""Derived field helpers persisted on write (VAT, totals, net due)."""
from decimal import Decimal

from app.calculations.money import D, money

HUNDRED = Decimal("100")


def vat_amount(amount_try, vat_rate) -> Decimal:
    return money(D(amount_try) * D(vat_rate) / HUNDRED)


def total_with_vat(amount_try, vat_rate) -> Decimal:
    return money(D(amount_try) + vat_amount(amount_try, vat_rate))


def invoice_net_due(amount_try, vat_rate, retention_amount_try) -> Decimal:
    """Net due to us = total incl. VAT − retention (Section 4.4)."""
    return money(total_with_vat(amount_try, vat_rate) - D(retention_amount_try))


def coerce_confidence(value) -> float | None:
    """Normalise an AI extraction-confidence score to a float in [0, 1], or None.

    Unparseable / missing values become None (unknown); out-of-range values are
    clamped. Used wherever the AI's 0–1 score is persisted (document capture,
    auto-file approval, AI Excel import)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(0.0, min(1.0, f))
