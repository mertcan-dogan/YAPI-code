"""AI Asistan conversation history — per-user, synced across devices.

Stores each user's chat conversations server-side so history follows the user to
any device. Conversations are private to the owning user; isolation is enforced
in application code (user_id + company_id) on top of RLS parity.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser
from app.models.ai_conversation import AIConversation
from app.responses import APIError, success

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_MESSAGES = 500


class Message(BaseModel):
    role: str
    text: str
    at: str | None = None
    # CR-007 fix: persist agent extras on `ai` messages so charts + citation chips
    # survive reload (messages is JSONB — no migration). Snapshots, frozen at ask
    # time (same semantics as pinned workspace items).
    charts: list | None = None
    citations: list | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("user", "ai"):
            raise ValueError("role must be 'user' or 'ai'")
        return v

    @field_validator("charts")
    @classmethod
    def _charts(cls, v):
        """Validate each chart against the CR-007-C ChartSpec (reused) and store the
        normalised form, so a rehydrated chart re-renders identically."""
        if v is None:
            return v
        from app.schemas.chart import ChartSpec, ValidationError

        cleaned = []
        for spec in v:
            try:
                cleaned.append(ChartSpec(**spec).model_dump())
            except (ValidationError, TypeError) as exc:
                raise ValueError("geçersiz grafik tanımı") from exc
        return cleaned


class ConversationUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(default_factory=list)
    project_id: uuid.UUID | None = None

    @field_validator("messages")
    @classmethod
    def _cap(cls, v: list) -> list:
        if len(v) > MAX_MESSAGES:
            raise ValueError(f"en fazla {MAX_MESSAGES} mesaj")
        return v


def _serialize(c: AIConversation) -> dict:
    return {
        "id": str(c.id),
        "title": c.title,
        "messages": c.messages or [],
        "project_id": str(c.project_id) if c.project_id else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _owned(user):
    return (
        AIConversation.company_id == user.company_id,
        AIConversation.user_id == user.id,
        AIConversation.is_deleted.is_(False),
    )


@router.get("/conversations")
def list_conversations(user: CurrentUser, db: Session = Depends(get_db)):
    """The user's conversations, most recently updated first."""
    rows = db.execute(
        select(AIConversation).where(*_owned(user)).order_by(AIConversation.updated_at.desc()).limit(200)
    ).scalars().all()
    return success([_serialize(c) for c in rows])


@router.put("/conversations/{conv_id}")
def upsert_conversation(
    conv_id: uuid.UUID, payload: ConversationUpsert, user: CurrentUser, db: Session = Depends(get_db)
):
    """Create or update a conversation by its (client-generated) id."""
    existing = db.execute(
        select(AIConversation).where(
            AIConversation.id == conv_id,
            AIConversation.company_id == user.company_id,
            AIConversation.user_id == user.id,
        )
    ).scalar_one_or_none()

    messages = [m.model_dump(exclude_none=True) for m in payload.messages]
    now = datetime.now(timezone.utc)

    if existing is None:
        conv = AIConversation(
            id=conv_id,
            company_id=user.company_id,
            user_id=user.id,
            title=payload.title,
            messages=messages,
            project_id=payload.project_id,
        )
        db.add(conv)
    else:
        existing.title = payload.title
        existing.messages = messages
        existing.project_id = payload.project_id
        existing.is_deleted = False
        existing.deleted_at = None
        existing.updated_at = now
        conv = existing

    db.commit()
    db.refresh(conv)
    return success(_serialize(conv))


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: uuid.UUID, user: CurrentUser, db: Session = Depends(get_db)):
    conv = db.execute(
        select(AIConversation).where(AIConversation.id == conv_id, *_owned(user))
    ).scalar_one_or_none()
    if conv is None:
        raise APIError(404, "NOT_FOUND", "Sohbet bulunamadı")
    conv.is_deleted = True
    conv.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return success({"deleted": str(conv_id)})
