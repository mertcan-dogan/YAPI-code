"""Subcontractor calculations (Section 7.1)."""
from decimal import Decimal

from app.calculations.money import D, money


def subcontractor_revised_contract(contract_value_try, approved_variations_try) -> Decimal:
    """Revised contract = contract value + approved variations."""
    return money(D(contract_value_try) + D(approved_variations_try))


def subcontractor_retention_held(total_paid_try, retention_pct) -> Decimal:
    """Retention held = total_paid × retention_pct / 100."""
    return money(D(total_paid_try) * D(retention_pct) / Decimal("100"))
