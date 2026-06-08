"""CR-002-E data repair: recompute auto-generated equipment cost_entries.

Earlier auto-created equipment cost entries used a wrong duration/VAT formula.
This script matches each equipment_log row to its '... otomatik oluşturuldu'
cost_entry (by project, category and equipment name) and recomputes
amount_try / vat_amount_try / total_with_vat_try with the corrected formula.

Run from backend/ with .env populated:

    python scripts/fix_equipment_costs.py            # apply
    python scripts/fix_equipment_costs.py --dry-run  # preview only
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from decimal import Decimal

from sqlalchemy import select

from app.calculations.equipment import equipment_cost
from app.calculations.money import money
from app.db import SessionLocal
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog

MARKER = "otomatik oluşturuldu"


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    fixed = 0
    try:
        equipment = db.execute(select(EquipmentLog).where(EquipmentLog.is_deleted.is_(False))).scalars().all()
        for e in equipment:
            category = "equipment_rented" if e.ownership_type == "rented" else "equipment_owned"
            entries = db.execute(
                select(CostEntry).where(
                    CostEntry.project_id == e.project_id,
                    CostEntry.cost_category == category,
                    CostEntry.is_deleted.is_(False),
                )
            ).scalars().all()
            for c in entries:
                desc = c.description or ""
                if MARKER not in desc or not desc.startswith(e.equipment_name):
                    continue
                amount = equipment_cost(
                    e.ownership_type, e.rate_try, e.rate_unit, e.deployment_start,
                    e.deployment_end, e.fuel_maintenance_try,
                )
                vat = money(amount * Decimal(20) / Decimal(100))
                total = money(amount + vat)
                if c.amount_try != amount or c.total_with_vat_try != total:
                    print(f"  {e.equipment_name}: {c.amount_try} -> {amount} (total {c.total_with_vat_try} -> {total})")
                    if not dry:
                        c.amount_try = amount
                        c.vat_rate = Decimal(20)
                        c.vat_amount_try = vat
                        c.total_with_vat_try = total
                    fixed += 1
        if dry:
            print(f"\n[DRY-RUN] {fixed} entries would be corrected. Re-run without --dry-run to apply.")
        else:
            db.commit()
            print(f"\n[DONE] {fixed} equipment cost entries recomputed.")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
