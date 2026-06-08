"""CR-002-E: corrected equipment cost formula."""
from datetime import date
from decimal import Decimal

from app.calculations.equipment import (
    equipment_cost,
    equipment_duration_days,
    equipment_duration_months,
)
from app.constants import ROLE_DIRECTOR


def test_inclusive_day_count():
    # 01.01 -> 20.01 inclusive = 20 days.
    assert equipment_duration_days(date(2025, 1, 1), date(2025, 1, 20)) == 20


def test_day_rate_cost():
    # 20 days * 8500 = 170,000 (no fuel)
    cost = equipment_cost("rented", 8500, "day", date(2025, 1, 1), date(2025, 1, 20), 0)
    assert cost == Decimal("170000.00")


def test_month_rate_cost():
    # 3 months * 45000 = 135,000
    assert equipment_duration_months(date(2025, 1, 1), date(2025, 4, 1)) == 3
    cost = equipment_cost("rented", 45000, "month", date(2025, 1, 1), date(2025, 4, 1), 0)
    assert cost == Decimal("135000.00")


def test_month_minimum_one():
    # Less than a full month still counts as 1.
    assert equipment_duration_months(date(2025, 1, 1), date(2025, 1, 10)) == 1


def test_fuel_maintenance_added():
    cost = equipment_cost("rented", 8500, "day", date(2025, 1, 1), date(2025, 1, 20), 5000)
    assert cost == Decimal("175000.00")  # 170,000 + 5,000


def test_auto_entry_amount_and_vat(client, seed):
    client.login(seed["a"]["users"][ROLE_DIRECTOR])
    pid = seed["a"]["project"].id
    client.post(
        f"/api/v1/projects/{pid}/equipment",
        json={"equipment_name": "Ekskavatör CAT320D", "ownership_type": "rented", "rate_try": "8500",
              "rate_unit": "day", "deployment_start": "2025-01-01", "deployment_end": "2025-01-20",
              "add_to_budget": True},
    )
    costs = client.get(f"/api/v1/projects/{pid}/costs").json()["data"]
    auto = next(c for c in costs if "otomatik oluşturuldu" in (c["description"] or ""))
    assert auto["amount_try"] == "170000.00"
    assert auto["total_with_vat_try"] == "204000.00"  # ×1.20
    assert "2025-01-01 - 2025-01-20" in auto["description"]
