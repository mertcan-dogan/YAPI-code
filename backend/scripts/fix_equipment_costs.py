"""CR-002-E / CR-003-E data repair: recompute auto-generated equipment cost entries.

Matches each equipment_log row to its '… otomatik oluşturuldu' cost_entry and
recomputes amount_try / vat_amount_try / total_with_vat_try with the corrected
inclusive-day / relativedelta-month formula. Writes an audit_log row for every
change (CR-003-E).

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
from sqlalchemy.orm import Session

from app.calculations.equipment import equipment_cost
from app.calculations.money import money
from app.db import SessionLocal
from app.models.cost_entry import CostEntry
from app.models.equipment_log import EquipmentLog
from app.services.audit import record_audit, snapshot

MARKER = "otomatik oluşturuldu"


def recompute_equipment_costs(db: Session, apply: bool = True) -> list[dict]:
    """Recompute matched equipment cost entries. Returns a list of change dicts.

    Matching is robust: an entry is claimed by exactly one equipment row (the
    most specific name match), avoiding double-processing across runs.
    """
    equipment = db.execute(select(EquipmentLog).where(EquipmentLog.is_deleted.is_(False))).scalars().all()
    # Longest names first so "Vinç 80 Ton" wins over "Vinç" for the same prefix.
    equipment.sort(key=lambda e: len(e.equipment_name or ""), reverse=True)

    claimed: set = set()
    changes: list[dict] = []
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
            if c.id in claimed:
                continue
            desc = (c.description or "").strip()
            if MARKER not in desc or not desc.startswith(e.equipment_name):
                continue
            claimed.add(c.id)
            amount = equipment_cost(
                e.ownership_type, e.rate_try, e.rate_unit, e.deployment_start,
                e.deployment_end, e.fuel_maintenance_try,
            )
            vat = money(amount * Decimal(20) / Decimal(100))
            total = money(amount + vat)
            if c.amount_try == amount and c.total_with_vat_try == total:
                continue
            changes.append({
                "equipment": e.equipment_name,
                "old_amount": str(c.amount_try),
                "new_amount": str(amount),
            })
            if apply:
                old = snapshot(c)
                c.amount_try = amount
                c.vat_rate = Decimal(20)
                c.vat_amount_try = vat
                c.total_with_vat_try = total
                record_audit(
                    db, company_id=c.company_id, user_id=c.created_by, table_name="cost_entries",
                    record_id=c.id, action="UPDATE", old_values=old, new_values=snapshot(c),
                )
    if apply:
        db.flush()
    return changes


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    try:
        changes = recompute_equipment_costs(db, apply=not dry)
        for ch in changes:
            print(f"  {ch['equipment']}: {ch['old_amount']} -> {ch['new_amount']}")
        if dry:
            print(f"\n[DRY-RUN] {len(changes)} kayıt düzeltilecek. Uygulamak için --dry-run olmadan çalıştırın.")
        else:
            db.commit()
            print(f"\n[DONE] {len(changes)} ekipman maliyet kaydı yeniden hesaplandı (audit_log'a yazıldı).")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
