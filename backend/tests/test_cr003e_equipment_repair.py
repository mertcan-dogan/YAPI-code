"""CR-003-E: equipment cost repair script recomputes + audits."""
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, __file__.rsplit("tests", 1)[0] + "scripts")

from scripts.fix_equipment_costs import recompute_equipment_costs  # noqa: E402

from app.models.audit_log import AuditLog
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog


def _setup(db, seed):
    a = seed["a"]
    eq = EquipmentLog(
        project_id=a["project"].id, company_id=a["company"].id,
        equipment_name="Kazık Çakma Makinesi", ownership_type="rented",
        rate_try=Decimal("35000"), rate_unit="day",
        deployment_start=date(2026, 1, 1), deployment_end=date(2026, 2, 28),  # 59 days inclusive
        fuel_maintenance_try=Decimal("0"),
    )
    db.add(eq)
    # A wrongly-valued auto entry.
    entry = CostEntry(
        project_id=a["project"].id, company_id=a["company"].id, created_by=a["users"]["director"].id,
        entry_date=date(2026, 1, 1), cost_category="equipment_rented",
        description="Kazık Çakma Makinesi — 2026-01-01 - 2026-02-28 — otomatik oluşturuldu",
        amount_try=Decimal("2038000"), vat_rate=Decimal("20"),
        vat_amount_try=Decimal("407600"), total_with_vat_try=Decimal("2445600"),
        entry_type="committed",
    )
    db.add(entry)
    db.flush()
    return eq, entry


def test_repair_recomputes_wrong_amount(db, seed):
    _eq, entry = _setup(db, seed)
    changes = recompute_equipment_costs(db, apply=True)
    db.refresh(entry)
    # 59 days * 35,000 = 2,065,000
    assert entry.amount_try == Decimal("2065000.00")
    assert entry.total_with_vat_try == Decimal("2478000.00")  # ×1.20
    assert len(changes) == 1


def test_repair_writes_audit_log(db, seed):
    _setup(db, seed)
    recompute_equipment_costs(db, apply=True)
    rows = db.query(AuditLog).filter(AuditLog.table_name == "cost_entries", AuditLog.action == "UPDATE").all()
    assert len(rows) >= 1


def test_repair_dry_run_no_change(db, seed):
    _eq, entry = _setup(db, seed)
    changes = recompute_equipment_costs(db, apply=False)
    db.refresh(entry)
    assert entry.amount_try == Decimal("2038000")  # unchanged in dry-run
    assert len(changes) == 1
