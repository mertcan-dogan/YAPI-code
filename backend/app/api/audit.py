"""Audit log router — read-only, director only (Section 2.5, 8.2)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import DirectorUser
from app.models.audit_log import AuditLog
from app.responses import success

router = APIRouter(tags=["audit"])


@router.get("/audit-log")
def get_audit_log(
    user: DirectorUser,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    table_name: str | None = None,
):
    stmt = select(AuditLog).where(AuditLog.company_id == user.company_id)
    if table_name:
        stmt = stmt.where(AuditLog.table_name == table_name)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()
    data = [
        {
            "id": str(r.id),
            "user_id": str(r.user_id) if r.user_id else None,
            "table_name": r.table_name,
            "record_id": str(r.record_id),
            "action": r.action,
            "old_values": r.old_values,
            "new_values": r.new_values,
            "ip_address": str(r.ip_address) if r.ip_address else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return success(data, meta={"total": total, "page": page, "per_page": per_page})
