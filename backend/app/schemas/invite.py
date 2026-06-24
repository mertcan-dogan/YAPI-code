"""Invite schemas (CR-041 teammate invitation/acceptance)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.constants import ROLES
from app.schemas.common import ORMModel


class InviteCreate(BaseModel):
    """Director creates an invite for an email + role."""

    email: EmailStr
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("Geçersiz kullanıcı rolü")
        return v


class InviteOut(ORMModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    invited_by: uuid.UUID
    expires_at: datetime
    created_at: datetime


class InviteAccept(BaseModel):
    """Body for POST /auth/invite/{token}/accept. The email + role come from the
    invite itself (authoritative); only the display name is collected here."""

    full_name: str | None = None
