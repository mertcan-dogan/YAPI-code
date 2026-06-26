"""Project closeout service — the Turkish acceptance lifecycle + the freeze rule.

Lifecycle (all stage actions + reopen are director-only and audited at the API
layer): Aktif → Geçici Kabul → Kesin Hesap → Kesin Kabul.

THE FREEZE RULE (core correctness point): the closeout report reflects a
point-in-time SNAPSHOT, never live data. At KESİN HESAP we call the existing
``build_project_report_data`` ONCE and store its returned dict in
``project_closeouts.report_data`` (JSONB) with ``frozen_at`` set. The PDF is
regenerated on demand from that frozen dict via ``_project_report_pdf`` — we never
recompute a finalized closeout from live data. This module only READS the report
engine and the financial calc; it never mutates them.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    CLOSEOUT_GECICI_KABUL,
    CLOSEOUT_KESIN_HESAP,
    CLOSEOUT_KESIN_KABUL,
)
from app.models.client_invoice import ClientInvoice
from app.models.closeout import ProjectCloseout
from app.models.company import Company
from app.models.cost_entry import CostEntry
from app.models.project import Project
from app.responses import APIError


def get_active_closeout(db: Session, project: Project) -> ProjectCloseout | None:
    """The single active (non-reopened) closeout row for the project, if any."""
    return db.execute(
        select(ProjectCloseout)
        .where(
            ProjectCloseout.project_id == project.id,
            ProjectCloseout.company_id == project.company_id,
            ProjectCloseout.is_active.is_(True),
        )
        .order_by(ProjectCloseout.created_at.desc())
    ).scalars().first()


def list_closeouts(db: Session, project: Project) -> list[ProjectCloseout]:
    """Full archive (active + reopened history) for the project, newest first."""
    return list(
        db.execute(
            select(ProjectCloseout)
            .where(
                ProjectCloseout.project_id == project.id,
                ProjectCloseout.company_id == project.company_id,
            )
            .order_by(ProjectCloseout.created_at.desc())
        ).scalars().all()
    )


def start_gecici_kabul(db: Session, project: Project, on_date: date, user_id: uuid.UUID) -> ProjectCloseout:
    """Geçici Kabul: open a new closeout, mark the project completed + actual end."""
    existing = get_active_closeout(db, project)
    if existing is not None:
        raise APIError(409, "CLOSEOUT_EXISTS", "Bu projede zaten aktif bir kapanış süreci var")
    closeout = ProjectCloseout(
        company_id=project.company_id,
        project_id=project.id,
        stage=CLOSEOUT_GECICI_KABUL,
        gecici_kabul_date=on_date,
        is_active=True,
        created_by=user_id,
    )
    db.add(closeout)
    project.status = "completed"
    project.actual_end_date = on_date
    db.flush()
    return closeout


def advance_kesin_hesap(
    db: Session, project: Project, company: Company, on_date: date
) -> ProjectCloseout:
    """Kesin Hesap: FREEZE the report snapshot, then advance the stage.

    Allowed from Geçici Kabul (first freeze) AND from Kesin Hesap itself — the
    latter is the director-driven RE-FREEZE (regenerate) when the report went
    stale (costs/invoices changed after frozen_at). Re-freezing rebuilds
    report_data + frozen_at from current live data; the stage stays kesin_hesap.
    Rejected before Geçici Kabul and after Kesin Kabul (fully closed).
    """
    closeout = get_active_closeout(db, project)
    if closeout is None or closeout.stage not in (CLOSEOUT_GECICI_KABUL, CLOSEOUT_KESIN_HESAP):
        raise APIError(409, "INVALID_STAGE", "Kesin hesap için önce geçici kabul gerekir")
    # Freeze ONCE — render the report data dict from the live engine and store it.
    # build_project_report_data returns a fully JSON-serialisable dict (formatted
    # strings); a finalized closeout is NEVER recomputed from live data afterwards.
    from app.services.reports import build_project_report_data

    closeout.report_data = build_project_report_data(db, project, company)
    closeout.frozen_at = datetime.now(timezone.utc)
    closeout.stage = CLOSEOUT_KESIN_HESAP
    closeout.kesin_hesap_date = on_date
    db.flush()
    return closeout


def advance_kesin_kabul(db: Session, project: Project, on_date: date) -> ProjectCloseout:
    """Kesin Kabul: the project is fully closed."""
    closeout = get_active_closeout(db, project)
    if closeout is None or closeout.stage != CLOSEOUT_KESIN_HESAP:
        raise APIError(409, "INVALID_STAGE", "Kesin kabul için önce kesin hesap gerekir")
    closeout.stage = CLOSEOUT_KESIN_KABUL
    closeout.kesin_kabul_date = on_date
    db.flush()
    return closeout


def reopen(db: Session, project: Project, user_id: uuid.UUID) -> ProjectCloseout:
    """Reopen: project back to active; the current closeout is archived (kept)."""
    closeout = get_active_closeout(db, project)
    if closeout is None:
        raise APIError(409, "NO_CLOSEOUT", "Bu projede yeniden açılacak bir kapanış yok")
    closeout.is_active = False
    closeout.reopened_at = datetime.now(timezone.utc)
    closeout.reopened_by = user_id
    project.status = "active"
    db.flush()
    return closeout


def report_is_stale(db: Session, project: Project, closeout: ProjectCloseout) -> bool:
    """Nice-to-have: has any cost/invoice changed AFTER the snapshot was frozen?

    Lets the director know the frozen "Proje Sonu Raporu" no longer matches live
    data so they can re-freeze (regenerate). We NEVER auto-mutate the snapshot.
    Returns False when nothing is frozen yet.
    """
    if closeout is None or closeout.frozen_at is None:
        return False
    latest_cost = db.execute(
        select(func.max(CostEntry.updated_at)).where(
            CostEntry.project_id == project.id,
            CostEntry.is_deleted.is_(False),
        )
    ).scalar()
    latest_inv = db.execute(
        select(func.max(ClientInvoice.updated_at)).where(
            ClientInvoice.project_id == project.id,
            ClientInvoice.is_deleted.is_(False),
        )
    ).scalar()
    for ts in (latest_cost, latest_inv):
        if ts is not None and _aware(ts) > _aware(closeout.frozen_at):
            return True
    return False


def _aware(dt: datetime) -> datetime:
    """Treat naive timestamps (SQLite) as UTC so comparisons never raise."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def summary_from_report(closeout: ProjectCloseout | None) -> dict | None:
    """Compact headline read off the FROZEN report_data (never live recompute)."""
    if closeout is None or not closeout.report_data:
        return None
    d = closeout.report_data
    return {
        "project_name": d.get("project_name"),
        "client_name": d.get("client_name"),
        "contract_value": d.get("contract_value"),
        "total_actual": d.get("total_actual"),
        "forecast_final": d.get("forecast_final"),
        "margin_pct": d.get("margin_pct"),
        "net_cash": d.get("net_cash"),
        "report_date": d.get("report_date"),
        "generated_at": d.get("generated_at"),
    }
