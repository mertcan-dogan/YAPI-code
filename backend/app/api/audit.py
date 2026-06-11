"""Audit log router — read-only, director only (Section 2.5, 8.2 + CR-001-H)."""
import io
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import DirectorUser
from app.models.audit_log import AuditLog
from app.models.user import User
from app.responses import success

router = APIRouter(tags=["audit"])

# Turkish labels (CR-001-H).
ACTION_LABELS = {"INSERT": "Eklendi", "UPDATE": "Güncellendi", "DELETE": "Silindi"}
TABLE_LABELS = {
    "cost_entries": "Maliyet Girişi",
    "client_invoices": "Fatura",
    "subcontractors": "Alt Yüklenici",
    "budget_line_items": "Bütçe Kalemi",
    "projects": "Proje",
}


def _filtered(stmt, *, table_name, action, user_id, date_from, date_to):
    if table_name:
        stmt = stmt.where(AuditLog.table_name == table_name)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    return stmt


def _user_names(db: Session, company_id) -> dict:
    rows = db.execute(select(User).where(User.company_id == company_id)).scalars().all()
    return {u.id: u.full_name for u in rows}


# CR-005-E: audit rows used to dump the entire 31-field record. Surface only the
# fields that actually changed so the UI can show "alan: eski → yeni" instead of a
# raw JSON blob. These housekeeping columns always differ on UPDATE and are noise.
_IGNORED_DIFF_FIELDS = {"updated_at", "created_at", "id", "is_deleted"}


def compute_changed_fields(old_values, new_values) -> list[dict]:
    """Return [{field, old, new}] for keys whose value changed (UPDATE only).

    INSERT/DELETE carry a single-sided snapshot, not a field-level change, so they
    return an empty list — the action label ("Eklendi"/"Silindi") tells that story.
    """
    if not old_values or not new_values:
        return []
    changed = []
    for key in sorted(set(old_values) | set(new_values)):
        if key in _IGNORED_DIFF_FIELDS:
            continue
        old_v = old_values.get(key)
        new_v = new_values.get(key)
        if old_v != new_v:
            changed.append({"field": key, "old": old_v, "new": new_v})
    return changed


@router.get("/audit-log")
def get_audit_log(
    user: DirectorUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    table_name: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    base = select(AuditLog).where(AuditLog.company_id == user.company_id)
    base = _filtered(base, table_name=table_name, action=action, user_id=user_id, date_from=date_from, date_to=date_to)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(
        base.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    names = _user_names(db, user.company_id)
    data = [
        {
            "id": str(r.id),
            "user_id": str(r.user_id) if r.user_id else None,
            "user_name": names.get(r.user_id, "—"),
            "table_name": r.table_name,
            "table_label": TABLE_LABELS.get(r.table_name, r.table_name),
            "record_id": str(r.record_id),
            "action": r.action,
            "action_label": ACTION_LABELS.get(r.action, r.action),
            "old_values": r.old_values,
            "new_values": r.new_values,
            "changed_fields": compute_changed_fields(r.old_values, r.new_values),
            "ip_address": str(r.ip_address) if r.ip_address else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return success(data, meta={"total": total, "page": page, "per_page": per_page})


@router.get("/audit-log/export")
def export_audit_log(
    user: DirectorUser,
    db: Session = Depends(get_db),
    table_name: str | None = None,
    action: str | None = None,
    user_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """CR-001-H: export the filtered audit log to .xlsx."""
    from openpyxl import Workbook

    base = select(AuditLog).where(AuditLog.company_id == user.company_id)
    base = _filtered(base, table_name=table_name, action=action, user_id=user_id, date_from=date_from, date_to=date_to)
    rows = db.execute(base.order_by(AuditLog.created_at.desc())).scalars().all()
    names = _user_names(db, user.company_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Denetim İzi"
    ws.append(["Tarih & Saat", "Kullanıcı", "İşlem", "Kayıt Türü", "Eski Değer", "Yeni Değer"])
    for r in rows:
        ws.append([
            r.created_at.strftime("%d.%m.%Y %H:%M"),
            names.get(r.user_id, "—"),
            ACTION_LABELS.get(r.action, r.action),
            TABLE_LABELS.get(r.table_name, r.table_name),
            str(r.old_values) if r.old_values else "",
            str(r.new_values) if r.new_values else "",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="denetim-izi.xlsx"'},
    )
