"""Equipment cost calculations (Section 7.1 + CR-002-E)."""
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.calculations.money import D, money


def equipment_duration_days(deployment_start: date, deployment_end: date | None) -> int:
    """Inclusive day count: (end - start).days + 1 (CR-002-E).

    e.g. 01.01 -> 20.01 is 20 days. No end yet -> 0 (cost accrues once ended)."""
    if deployment_end is None:
        return 0
    return max((deployment_end - deployment_start).days + 1, 0)


def equipment_duration_months(deployment_start: date, deployment_end: date | None) -> int:
    """Whole months between the dates, minimum 1 (CR-002-E)."""
    if deployment_end is None:
        return 0
    rd = relativedelta(deployment_end, deployment_start)
    months = rd.months + rd.years * 12
    return max(1, months)


def equipment_cost(
    ownership_type: str,
    rate_try,
    rate_unit: str | None,
    deployment_start: date,
    deployment_end: date | None,
    fuel_maintenance_try=0,
) -> Decimal:
    """Equipment cost (excl. VAT).

    Rented (day):   rate × inclusive_days + fuel
    Rented (month): rate × whole_months(min 1) + fuel
    Owned:          fuel/maintenance only
    """
    fuel = D(fuel_maintenance_try)
    if ownership_type == "owned":
        return money(fuel)
    if deployment_end is None:
        # Cannot compute a duration yet — only fuel/maintenance is attributable.
        return money(fuel)

    rate = D(rate_try)
    if rate_unit == "month":
        units = D(equipment_duration_months(deployment_start, deployment_end))
    else:  # default 'day'
        units = D(equipment_duration_days(deployment_start, deployment_end))
    return money(rate * units + fuel)
