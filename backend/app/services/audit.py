"""Audit trail service (Section 8.2).

Every state change to projects, cost_entries, client_invoices,
subcontractors and budget_line_items writes an append-only audit_log row
capturing old/new values. Called from the write services within the same
DB transaction so the audit and the change commit atomically.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.constants import AUDITED_TABLES


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any]:
    """Build a JSON-serialisable dict of an ORM object's column values."""
    if obj is None:
        return {}
    cols = fields or [c.name for c in obj.__table__.columns]
    return {c: _jsonable(getattr(obj, c, None)) for c in cols}


def record_audit(
    db: Session,
    *,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None,
    table_name: str,
    record_id: uuid.UUID,
    action: str,
    old_values: dict | None = None,
    new_values: dict | None = None,
    ip_address: str | None = None,
) -> None:
    if table_name not in AUDITED_TABLES:
        return
    db.add(
        AuditLog(
            company_id=company_id,
            user_id=user_id,
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
        )
    )
