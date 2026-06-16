"""project_units schedule persistence + derived totals (CR-016-B).

The unit schedule (daire dağılımı) is upserted from the ``units`` array on project
create/update. Everything here is company-scoped: a forged ``company_id`` in the
request body can never apply — rows are always written with the caller's company,
and an ``id`` that isn't a live row of *this* project+company is treated as new
(so it cannot hijack another tenant's row).

``unit_count`` is derived = SUM(count) whenever a schedule exists; when no schedule
exists it is left manual (today's behavior for non-residential projects).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.models.project import Project
from app.models.project_unit import ProjectUnit


def _live_units(db: Session, project_id: uuid.UUID, company_id: uuid.UUID) -> list[ProjectUnit]:
    return list(
        db.execute(
            select(ProjectUnit).where(
                ProjectUnit.project_id == project_id,
                ProjectUnit.company_id == company_id,
                ProjectUnit.is_deleted.is_(False),
            )
        ).scalars().all()
    )


def sync_schedule(db: Session, project: Project, units_in, company_id: uuid.UUID) -> None:
    """UPSERT the schedule for ``project`` from a list of ``UnitScheduleIn``.

    - rows whose ``id`` matches a live row of this project+company are updated;
    - rows without a (matching) id are created;
    - live rows absent from the payload are soft-deleted.
    Then ``unit_count`` is re-derived.
    """
    existing = {u.id: u for u in _live_units(db, project.id, company_id)}
    seen: set[uuid.UUID] = set()

    for item in units_in:
        row = existing.get(item.id) if item.id is not None else None
        if row is not None:
            row.unit_type = item.unit_type
            row.custom_label = item.custom_label
            row.count = item.count
            row.gross_m2_each = item.gross_m2_each
            row.net_m2_each = item.net_m2_each
            row.sale_price_try = item.sale_price_try
            row.notes = item.notes
            seen.add(row.id)
        else:
            db.add(ProjectUnit(
                project_id=project.id,
                company_id=company_id,  # always the caller's — forged body id ignored
                unit_type=item.unit_type,
                custom_label=item.custom_label,
                count=item.count,
                gross_m2_each=item.gross_m2_each,
                net_m2_each=item.net_m2_each,
                sale_price_try=item.sale_price_try,
                notes=item.notes,
            ))

    # Soft-delete the rows that were removed.
    now = datetime.now(timezone.utc)
    for uid, row in existing.items():
        if uid not in seen:
            row.is_deleted = True
            row.deleted_at = now

    db.flush()
    _derive_unit_count(db, project, company_id)


def _derive_unit_count(db: Session, project: Project, company_id: uuid.UUID) -> None:
    """unit_count = SUM(count) when a schedule exists; leave manual otherwise."""
    rows = _live_units(db, project.id, company_id)
    if rows:
        project.unit_count = sum(r.count for r in rows)


def schedule_aggregates(units: list[ProjectUnit]) -> dict:
    """Computed (NOT stored) totals over a list of live unit rows.

    ``total_estimated_sales_try`` is None when no row carries a sale price (the
    schedule's estimated sales is informational and optional, §0.2 / §5).
    """
    total_units = 0
    gross = D(0)
    net = D(0)
    sales = D(0)
    has_sales = False
    for u in units:
        c = u.count or 0
        total_units += c
        gross += D(u.gross_m2_each) * c
        if u.net_m2_each is not None:
            net += D(u.net_m2_each) * c
        if u.sale_price_try is not None:
            sales += D(u.sale_price_try) * c
            has_sales = True
    return {
        "total_units": total_units,
        "total_sellable_gross_m2": money(gross),
        "total_sellable_net_m2": money(net),
        "total_estimated_sales_try": money(sales) if has_sales else None,
    }
