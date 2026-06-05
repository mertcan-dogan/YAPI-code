"""Decimal money helpers. All financial columns are DECIMAL(18,2)."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def D(value) -> Decimal:
    """Coerce any numeric-ish value to Decimal, treating None as 0."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def money(value) -> Decimal:
    """Quantize to 2 decimal places, half-up rounding."""
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def pct(value) -> Decimal:
    """Quantize a percentage to 2 decimal places."""
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def safe_div(numerator, denominator) -> Decimal:
    """Division that returns 0 instead of raising on a zero denominator.

    Used everywhere a contract value or budget could be zero (Section 7.3,
    8.1: no division by zero).
    """
    num = D(numerator)
    den = D(denominator)
    if den == ZERO:
        return ZERO
    return num / den
