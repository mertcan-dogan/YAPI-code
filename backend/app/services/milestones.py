"""Milestone schedule rollups (CR-019-A) — SCHEDULE lane only.

The weighted progress is computed with **SQL aggregation (SUM)**, never a Python
row loop (CR-007 governing principle + a perf requirement). We pull a handful of
scalar SUM/COUNT values from the database and do a single exact-``Decimal``
division per group in Python — there is no per-row iteration.

    schedule_progress_pct = SUM(weight WHERE status='done') / NULLIF(SUM(weight), 0) * 100

Unset/zero weights count as 1; a divide-by-zero (no milestones) yields ``None``.

**This module MUST NOT touch any monetary figure (CR-019 §0.2).** It produces
progress %, weights and counts only.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.calculations.money import D, money
from app.constants import MILESTONE_STATUS_DONE
from app.models.project_milestone import ProjectMilestone


def _effective_weight():
    """SQL expression: the milestone weight, with unset/zero treated as 1."""
    w = ProjectMilestone.weight
    return case((w > 0, w), else_=1)


def _conds(project_id: uuid.UUID, company_id: uuid.UUID):
    return (
        ProjectMilestone.project_id == project_id,
        ProjectMilestone.company_id == company_id,
        ProjectMilestone.is_deleted.is_(False),
    )


def _progress(done_weight: Decimal, total_weight: Decimal) -> str | None:
    """SUM(done) / SUM(total) * 100, guarded against divide-by-zero."""
    if total_weight <= 0:
        return None
    return str(money(D(done_weight) / D(total_weight) * Decimal("100")))


def compute_schedule_rollup(db: Session, project_id: uuid.UUID, company_id: uuid.UUID) -> dict:
    """Overall + per-stage weighted schedule progress, all via SQL SUM aggregation."""
    ew = _effective_weight()
    done_weight = func.coalesce(func.sum(case((ProjectMilestone.status == MILESTONE_STATUS_DONE, ew), else_=0)), 0)
    total_weight = func.coalesce(func.sum(ew), 0)
    done_count = func.coalesce(func.sum(case((ProjectMilestone.status == MILESTONE_STATUS_DONE, 1), else_=0)), 0)
    total_count = func.count(ProjectMilestone.id)

    conds = _conds(project_id, company_id)

    # --- Overall (one aggregate row) ---
    row = db.execute(
        select(done_weight, total_weight, done_count, total_count).where(*conds)
    ).one()
    dW, tW = D(row[0]), D(row[1])

    # --- Per-stage (GROUP BY stage) ---
    by_stage = []
    for s in db.execute(
        select(ProjectMilestone.stage, done_weight, total_weight, done_count, total_count)
        .where(*conds)
        .group_by(ProjectMilestone.stage)
        .order_by(ProjectMilestone.stage)
    ).all():
        by_stage.append({
            "stage": s[0],
            "progress_pct": _progress(D(s[1]), D(s[2])),
            "done": int(s[3] or 0),
            "total": int(s[4] or 0),
        })

    return {
        "schedule_progress_pct": _progress(dW, tW),
        "total": int(row[3] or 0),
        "done": int(row[2] or 0),
        "total_weight": str(money(tW)),
        "done_weight": str(money(dW)),
        "by_stage": by_stage,
    }


def _as_date(v) -> date | None:
    """Coerce a SQL min()/column result to a ``date`` (SQLite may hand back a str)."""
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def compute_schedule_block(
    db: Session,
    project_id: uuid.UUID,
    company_id: uuid.UUID,
    today: date | None = None,
) -> dict:
    """CR-019-B: the SCHEDULE-lane dashboard block.

    ``{ schedule_progress_pct, total, done, next_deadline, overdue_count,
        by_stage:[{stage, progress_pct, done, total, deadline}] }``

    overdue = ``status != 'done' AND planned_date < today``;
    next_deadline = earliest FUTURE (``>= today``) planned_date among not-done.
    Per-stage ``deadline`` = earliest not-done planned_date in that stage (may be
    past if the stage is overdue). Date comparisons are dialect-safe: ISO ``Date``
    columns compare chronologically on both SQLite and Postgres.

    **SCHEDULE lane only — this block feeds display + Proje Sağlığı's "%
    Tamamlandı"; it MUST NOT enter any money calculation (§0.2).**
    """
    today = today or date.today()
    rollup = compute_schedule_rollup(db, project_id, company_id)
    conds = _conds(project_id, company_id)
    not_done = ProjectMilestone.status != MILESTONE_STATUS_DONE
    has_date = ProjectMilestone.planned_date.is_not(None)

    overdue_count = db.execute(
        select(func.count(ProjectMilestone.id)).where(
            *conds, not_done, has_date, ProjectMilestone.planned_date < today
        )
    ).scalar() or 0

    next_deadline = db.execute(
        select(func.min(ProjectMilestone.planned_date)).where(
            *conds, not_done, has_date, ProjectMilestone.planned_date >= today
        )
    ).scalar()

    # Per-stage nearest pending deadline (earliest not-done planned_date).
    stage_deadlines = {
        s[0]: _as_date(s[1])
        for s in db.execute(
            select(ProjectMilestone.stage, func.min(ProjectMilestone.planned_date))
            .where(*conds, not_done, has_date)
            .group_by(ProjectMilestone.stage)
        ).all()
    }

    by_stage = [
        {**st, "deadline": _iso(stage_deadlines.get(st["stage"]))}
        for st in rollup["by_stage"]
    ]

    return {
        "schedule_progress_pct": rollup["schedule_progress_pct"],
        "total": rollup["total"],
        "done": rollup["done"],
        "next_deadline": _iso(_as_date(next_deadline)),
        "overdue_count": int(overdue_count),
        "by_stage": by_stage,
    }
