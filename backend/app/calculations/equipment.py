"""Equipment cost calculations (Section 7.1)."""
from datetime import date
from decimal import Decimal

from app.calculations.money import D, money

# Average days per month, used to convert a monthly rate to a daily basis.
DAYS_PER_MONTH = Decimal("30")


def equipment_duration_days(deployment_start: date, deployment_end: date | None) -> int:
    """Deployment duration in days. Inclusive lower bound; if no end date,
    duration is 0 (still deployed — cost accrues only once an end is set)."""
    if deployment_end is None:
        return 0
    delta = (deployment_end - deployment_start).days
    return max(delta, 0)


def equipment_cost(
    ownership_type: str,
    rate_try,
    rate_unit: str | None,
    deployment_start: date,
    deployment_end: date | None,
    fuel_maintenance_try=0,
) -> Decimal:
    """Equipment cost.

    Rented:  rate_try × duration + fuel_maintenance_try
             where duration is in days (rate_unit='day') or months
             (rate_unit='month'), derived from the deployment dates.
    Owned:   only fuel/maintenance costs are attributed.
    """
    fuel = D(fuel_maintenance_try)
    if ownership_type == "owned":
        return money(fuel)

    days = equipment_duration_days(deployment_start, deployment_end)
    rate = D(rate_try)
    if rate_unit == "month":
        units = D(days) / DAYS_PER_MONTH
    else:  # default 'day'
        units = D(days)
    return money(rate * units + fuel)
