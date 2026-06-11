"""Bildirim zili router'ı (CR-006-C).

Şirket kapsamlı bildirim akışı: kullanıcıya özel (user_id eşleşen) veya tüm
şirkete açık (user_id NULL) bildirimleri döndürür. Okunmamışlar en üstte.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.notification import Notification
from app.responses import APIError, success

router = APIRouter(tags=["notifications"])

_TYPE_ROUTE = {
    "overdue_payment": "/reminders",
    "margin_warning": "/dashboard",
    "budget_overrun": "/budget",
    "invoice_received": "/cashflow",
}


def _visible(user):
    """Bildirim şirkete ait VE (herkese açık VEYA bu kullanıcıya özel)."""
    return (
        Notification.company_id == user.company_id,
        Notification.is_deleted.is_(False),
        or_(Notification.user_id.is_(None), Notification.user_id == user.id),
    )


def _serialize(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "body": n.body,
        "type": n.notification_type,
        "severity": n.severity,
        "is_read": n.is_read,
        "related_project_id": str(n.related_project_id) if n.related_project_id else None,
        "link": _TYPE_ROUTE.get(n.notification_type),
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
    }


@router.get("/notifications")
def list_notifications(user: CurrentUser, db: Session = Depends(get_db)):
    """Son 50 bildirim — okunmamışlar önce, ardından en yeni."""
    rows = db.execute(
        select(Notification)
        .where(*_visible(user))
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
        .limit(50)
    ).scalars().all()
    return success([_serialize(n) for n in rows])


@router.get("/notifications/unread-count")
def unread_count(user: CurrentUser, db: Session = Depends(get_db)):
    count = db.execute(
        select(func.count()).select_from(Notification).where(
            *_visible(user), Notification.is_read.is_(False)
        )
    ).scalar_one()
    return success({"count": int(count)})


def _get_owned(db: Session, user, notif_id: uuid.UUID) -> Notification:
    n = db.execute(
        select(Notification).where(Notification.id == notif_id, *_visible(user))
    ).scalar_one_or_none()
    if n is None:
        raise APIError(404, "NOT_FOUND", "Bildirim bulunamadı")
    return n


@router.put("/notifications/{notif_id}/read")
def mark_read(notif_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    n = _get_owned(db, user, notif_id)
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(n)
    return success(_serialize(n))


@router.put("/notifications/read-all")
def mark_all_read(user: CurrentUser, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Notification).where(*_visible(user), Notification.is_read.is_(False))
    ).scalars().all()
    for n in rows:
        n.is_read = True
        n.read_at = now
    db.commit()
    return success({"marked": len(rows)})


@router.delete("/notifications/{notif_id}")
def delete_notification(notif_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    n = _get_owned(db, user, notif_id)
    n.is_deleted = True
    n.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return success({"deleted": str(notif_id)})
