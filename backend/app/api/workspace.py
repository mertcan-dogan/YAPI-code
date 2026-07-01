"""CR-008-A/B — "Çalışma Alanım" per-user workspace of pinned snapshots.

Mirrors the ai_conversations pattern: per-user, company-scoped, soft-deleted,
client-generated id. Each item is a SNAPSHOT (frozen at pin time, §0.2). Chart
payloads reuse the CR-007-C ChartSpec validation so a pinned chart re-renders
identically. ``company_id``/``user_id`` always come from the authenticated user —
any values in the request body are ignored.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import CurrentUser
from app.middleware.limits import enforce_user_limit
from app.models.workspace_item import WorkspaceItem
from app.responses import APIError, success

router = APIRouter(prefix="/workspace", tags=["workspace"])

ITEM_TYPES = ("chart", "analysis")


def _rate_limit(user) -> None:
    enforce_user_limit(user.id, "workspace_write", settings.workspace_write_rate_per_minute)


class WorkspaceItemCreate(BaseModel):
    id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    item_type: str
    payload: dict
    source_conversation_id: uuid.UUID | None = None
    layout: dict | None = None


class WorkspaceItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    layout: dict | None = None


class LayoutCell(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    w: int
    h: int


class LayoutBulkUpdate(BaseModel):
    items: list[LayoutCell] = Field(default_factory=list)


def _validate_payload(item_type: str, payload: dict) -> dict:
    """Validate + normalise the snapshot by type. A chart must pass the same
    ChartSpec validation as CR-007-C; an analysis needs answer_markdown."""
    if item_type not in ITEM_TYPES:
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz öğe türü", field="item_type")
    if item_type == "chart":
        from app.schemas.chart import ChartSpec, ValidationError

        try:
            return ChartSpec(**(payload or {})).model_dump()
        except (ValidationError, TypeError) as exc:
            raise APIError(422, "VALIDATION_ERROR", "Geçersiz grafik tanımı", field="payload") from exc
    # analysis
    if not isinstance(payload, dict) or not (payload.get("answer_markdown") or "").strip():
        raise APIError(422, "VALIDATION_ERROR", "Analiz metni boş olamaz", field="payload")
    citations = payload.get("citations") or []
    if not isinstance(citations, list):
        raise APIError(422, "VALIDATION_ERROR", "Geçersiz atıf listesi", field="payload")
    return {"answer_markdown": payload["answer_markdown"], "citations": citations}


def _serialize(it: WorkspaceItem) -> dict:
    return {
        "id": str(it.id),
        "title": it.title,
        "item_type": it.item_type,
        "payload": it.payload or {},
        "source_conversation_id": str(it.source_conversation_id) if it.source_conversation_id else None,
        "layout": it.layout,
        "pinned_at": it.pinned_at.isoformat() if it.pinned_at else None,
        "created_at": it.created_at.isoformat() if it.created_at else None,
        "updated_at": it.updated_at.isoformat() if it.updated_at else None,
    }


def _owned(user):
    return (
        WorkspaceItem.company_id == user.company_id,
        WorkspaceItem.user_id == user.id,
        WorkspaceItem.is_deleted.is_(False),
    )


@router.get("/items")
def list_items(user: CurrentUser, db: Session = Depends(get_db)):
    """The current user's pinned items, newest first (the board grid uses layout)."""
    rows = db.execute(
        select(WorkspaceItem).where(*_owned(user)).order_by(WorkspaceItem.pinned_at.desc()).limit(200)
    ).scalars().all()
    return success([_serialize(r) for r in rows])


@router.post("/items")
def create_item(payload: WorkspaceItemCreate, user: CurrentUser, db: Session = Depends(get_db)):
    """Pin a snapshot. Client-generated id is accepted; a re-POST with the same id
    returns the existing item (idempotent-ish, so a double-click can't duplicate)."""
    _rate_limit(user)
    clean_payload = _validate_payload(payload.item_type, payload.payload)

    if payload.id is not None:
        existing = db.execute(
            select(WorkspaceItem).where(
                WorkspaceItem.id == payload.id,
                WorkspaceItem.company_id == user.company_id,
                WorkspaceItem.user_id == user.id,
                WorkspaceItem.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if existing is not None:
            return success(_serialize(existing))

    item = WorkspaceItem(
        id=payload.id or uuid.uuid4(),
        company_id=user.company_id,   # server-side only (body ignored)
        user_id=user.id,              # server-side only (body ignored)
        title=payload.title,
        item_type=payload.item_type,
        payload=clean_payload,
        source_conversation_id=payload.source_conversation_id,
        layout=payload.layout,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return success(_serialize(item))


@router.put("/layout")
def bulk_layout(payload: LayoutBulkUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    """CR-008-B: persist a drag/resize session atomically. Validates that every id
    belongs to the user BEFORE writing, so a foreign id rejects the whole batch
    without partial saves."""
    _rate_limit(user)
    if not payload.items:
        return success({"updated": 0})

    ids = [c.id for c in payload.items]
    owned = db.execute(
        select(WorkspaceItem).where(WorkspaceItem.id.in_(ids), *_owned(user))
    ).scalars().all()
    by_id = {it.id: it for it in owned}

    missing = [str(c.id) for c in payload.items if c.id not in by_id]
    if missing:
        # Reject the entire batch (no writes yet) — atomic.
        raise APIError(404, "NOT_FOUND", "Bazı öğeler bulunamadı veya size ait değil")

    now = datetime.now(timezone.utc)
    for c in payload.items:
        it = by_id[c.id]
        it.layout = {"x": c.x, "y": c.y, "w": c.w, "h": c.h}
        it.updated_at = now
    db.commit()
    return success({"updated": len(payload.items)})


@router.put("/items/{item_id}")
def update_item(item_id: uuid.UUID, payload: WorkspaceItemUpdate, user: CurrentUser, db: Session = Depends(get_db)):
    """Rename and/or move (layout cell) an owned item."""
    _rate_limit(user)
    item = db.execute(
        select(WorkspaceItem).where(WorkspaceItem.id == item_id, *_owned(user))
    ).scalar_one_or_none()
    if item is None:
        raise APIError(404, "NOT_FOUND", "Öğe bulunamadı")
    if payload.title is not None:
        item.title = payload.title
    if payload.layout is not None:
        item.layout = payload.layout
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return success(_serialize(item))


@router.delete("/items/{item_id}")
def delete_item(item_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    _rate_limit(user)
    item = db.execute(
        select(WorkspaceItem).where(WorkspaceItem.id == item_id, *_owned(user))
    ).scalar_one_or_none()
    if item is None:
        raise APIError(404, "NOT_FOUND", "Öğe bulunamadı")
    item.is_deleted = True
    item.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return success({"deleted": str(item_id)})
