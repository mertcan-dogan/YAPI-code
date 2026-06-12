"""Settings router — company & user management, director only (Section 11)."""
import uuid

import logging
import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.constants import ROLE_DIRECTOR
from app.db import get_db
from app.deps import CurrentUser, DirectorUser
from app.models.company import Company
from app.models.user import User
from app.responses import APIError, success
from app.schemas.user import CompanyOut, CompanyUpdate, UserInvite, UserOut, UserUpdate
from app.services.email import send_user_invitation

router = APIRouter(prefix="/settings", tags=["settings"])

# CR-006-D: company logo upload (Supabase Storage, public bucket).
logger = logging.getLogger(__name__)
LOGO_BUCKET = "company-logos"
LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2MB
LOGO_ALLOWED = {"image/png": "png", "image/jpeg": "jpg"}
_LOGO_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


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


@router.post("/company/logo")
async def upload_company_logo(
    user: DirectorUser,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Şirket logosunu yükle (PNG/JPEG, max 2MB) ve companies.logo_url güncelle."""
    if file.content_type not in LOGO_ALLOWED:
        raise APIError(422, "VALIDATION_ERROR",
                       "Sadece PNG veya JPEG yükleyebilirsiniz", field="file")
    data = await file.read()
    if len(data) > LOGO_MAX_BYTES:
        raise APIError(422, "VALIDATION_ERROR", "Logo en fazla 2MB olabilir", field="file")
    if not any(data.startswith(sig) for sig in _LOGO_MAGIC.get(file.content_type, ())):
        raise APIError(422, "VALIDATION_ERROR",
                       "Dosya içeriği belirtilen türle uyuşmuyor", field="file")

    if not app_settings.supabase_url or not app_settings.supabase_service_key:
        raise APIError(503, "STORAGE_UNAVAILABLE", "Dosya depolama yapılandırılmadı")

    ext = LOGO_ALLOWED[file.content_type]
    object_path = f"company_logos/{user.company_id}/logo.{ext}"
    url = f"{app_settings.supabase_url}/storage/v1/object/{LOGO_BUCKET}/{object_path}"
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {app_settings.supabase_service_key}",
                "Content-Type": file.content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )
    except httpx.HTTPError:
        raise APIError(502, "STORAGE_ERROR", "Logo yüklenemedi")
    if resp.status_code not in (200, 201):
        # Surface the upstream status so misconfiguration (e.g. wrong service
        # key) is diagnosable instead of a generic failure.
        logger.error("Logo upload failed: storage %s %s", resp.status_code, resp.text[:300])
        raise APIError(502, "STORAGE_ERROR", f"Logo yüklenemedi (depolama hatası {resp.status_code})")

    public_url = (
        f"{app_settings.supabase_url}/storage/v1/object/public/{LOGO_BUCKET}/{object_path}"
    )
    company = db.get(Company, user.company_id)
    company.logo_url = public_url
    db.commit()
    db.refresh(company)
    return success(CompanyOut.model_validate(company).model_dump(mode="json"))


@router.delete("/company/logo")
def delete_company_logo(user: DirectorUser, db: Session = Depends(get_db)):
    """Şirket logosunu kaldır — depolamadan sil ve logo_url'i temizle."""
    company = db.get(Company, user.company_id)
    if company.logo_url and app_settings.supabase_url and app_settings.supabase_service_key:
        # Best-effort delete; never fail the request if storage cleanup errors.
        for ext in ("png", "jpg"):
            object_path = f"company_logos/{user.company_id}/logo.{ext}"
            try:
                httpx.request(
                    "DELETE",
                    f"{app_settings.supabase_url}/storage/v1/object/{LOGO_BUCKET}/{object_path}",
                    headers={"Authorization": f"Bearer {app_settings.supabase_service_key}"},
                    timeout=15,
                )
            except httpx.HTTPError:
                pass
    company.logo_url = None
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


from typing import Any  # noqa: E402

from pydantic import BaseModel  # noqa: E402


class DashboardLayoutIn(BaseModel):
    layout: Any


@router.get("/dashboard-layout")
def get_dashboard_layout(user: CurrentUser, db: Session = Depends(get_db)):
    """The current user's saved Ana Sayfa widget layout (null = use default)."""
    u = db.get(User, user.id)
    return success({"layout": u.dashboard_layout if u else None})


@router.put("/dashboard-layout")
def set_dashboard_layout(payload: DashboardLayoutIn, user: CurrentUser, db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if u is None:
        raise APIError(404, "NOT_FOUND", "Kullanıcı bulunamadı")
    u.dashboard_layout = payload.layout
    db.commit()
    return success({"layout": u.dashboard_layout})
