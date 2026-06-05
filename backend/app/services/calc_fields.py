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
