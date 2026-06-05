"""Settings router — company & user management, director only (Section 11)."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import ROLE_DIRECTOR
from app.db import get_db
from app.deps import DirectorUser
from app.models.company import Company
from app.models.user import User
from app.responses import APIError, success
from app.schemas.user import CompanyOut, CompanyUpdate, UserInvite, UserOut, UserUpdate
from app.services.email import send_user_invitation

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/company")
def get_company(user: DirectorUser, db: Session = Depends(get_db)):
    company = db.get(Company, user.company_id)
    return success(CompanyOut.model_validate(company).model_dump(mode="json"))


@router.put("/company")
def update_company(
    payload: CompanyUpdate,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    company = db.get(Company, user.company_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    db.commit()
    db.refresh(company)
    return success(CompanyOut.model_validate(company).model_dump(mode="json"))


@router.get("/users")
def list_users(user: DirectorUser, db: Session = Depends(get_db)):
    rows = db.execute(
        select(User).where(User.company_id == user.company_id, User.is_deleted.is_(False))
    ).scalars().all()
    return success([UserOut.model_validate(u).model_dump(mode="json") for u in rows])


@router.post("/users")
def invite_user(
    payload: UserInvite,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing is not None:
        raise APIError(422, "VALIDATION_ERROR", "Bu e-posta zaten kayıtlı", field="email")
    company = db.get(Company, user.company_id)
    # The Supabase auth user is created out-of-band via the invite email link.
    send_user_invitation(payload.email, payload.full_name, company.name)
    return success(
        {"email": payload.email, "message": f"{payload.email} adresine davet gönderildi"}
    )


@router.put("/users/{user_id}")
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    user: DirectorUser,
    db: Session = Depends(get_db),
):
    target = db.execute(
        select(User).where(
            User.id == user_id, User.company_id == user.company_id, User.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if target is None:
        raise APIError(404, "NOT_FOUND", "Kullanıcı bulunamadı")

    changes = payload.model_dump(exclude_unset=True)
    # Cannot deactivate your own account (Section 11).
    if changes.get("is_active") is False and target.id == user.id:
        raise APIError(422, "VALIDATION_ERROR", "Kendi hesabınızı pasifleştiremezsiniz")

    # Cannot remove the last active director (Section 11).
    deactivating = changes.get("is_active") is False or (changes.get("role") and changes["role"] != ROLE_DIRECTOR)
    if target.role == ROLE_DIRECTOR and deactivating:
        active_directors = db.execute(
            select(func.count()).select_from(User).where(
                User.company_id == user.company_id,
                User.role == ROLE_DIRECTOR,
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        ).scalar_one()
        if active_directors <= 1:
            raise APIError(422, "VALIDATION_ERROR", "En az bir aktif yönetici bulunmalıdır")

    for k, v in changes.items():
        setattr(target, k, v)
    db.commit()
    db.refresh(target)
    return success(UserOut.model_validate(target).model_dump(mode="json"))
