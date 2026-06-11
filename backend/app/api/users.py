"""Kullanıcı yönetimi router'ı (CR-006-B: şirkete davet)."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ROLES, ROLE_SITE_MANAGER
from app.db import get_db
from app.deps import DirectorUser
from app.models.company import Company
from app.models.user import User
from app.responses import APIError, success
from app.services.email_service import email_service

router = APIRouter(tags=["users"])


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = ROLE_SITE_MANAGER

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("Geçersiz rol")
        return v


@router.post("/users/invite")
def invite_user(
    payload: InviteCreate,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    """Şirkete yeni kullanıcı davet et — davet e-postası gönderir (yalnızca Direktör).

    Davet token'ı (UUID, 7 gün geçerli) oluşturulur ve
    {FRONTEND_URL}/accept-invite?token={token} bağlantısı e-posta ile gönderilir.
    """
    email = payload.email.lower()
    existing = db.execute(
        select(User).where(User.email == email, User.is_deleted.is_(False))
    ).scalar_one_or_none()
    if existing is not None:
        raise APIError(409, "ALREADY_EXISTS", "Bu e-posta adresi zaten kayıtlı")

    company = db.get(Company, user.company_id)
    company_name = company.name if company else "Yapı"
    invite_token = str(uuid.uuid4())

    result = email_service.send_user_invitation_email(email, company_name, invite_token)
    return success({
        "invited_email": email,
        "role": payload.role,
        "email_sent": bool(result.get("sent")),
    })
