"""Auth router (Section 2.5, 3.1). Authentication is delegated to Supabase Auth.

/auth/login proxies the password grant to Supabase (the only way the backend
ever sees a password — it is never stored). The frontend may alternatively use
the Supabase JS client directly; either way the backend only ever validates the
resulting JWT.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ROLE_DIRECTOR
from app.db import AdminSessionLocal, get_db
from app.deps import CurrentUser, TokenClaims
from app.models.company import Company
from app.models.user import User
from app.responses import APIError, success
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    company_name: str
    full_name: str
    email: EmailStr | None = None  # falls back to the email claim in the token


def _unique_slug(db: Session, name: str) -> str:
    base = slugify(name)[:90] or "sirket"
    slug = base
    while db.execute(select(Company).where(Company.slug == slug)).scalar_one_or_none() is not None:
        slug = f"{base}-{uuid.uuid4().hex[:6]}"
    return slug


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    from app.middleware.limits import clear_failed_logins, is_login_locked, record_failed_login

    ip = request.client.host if request.client else "unknown"
    # CR-002-I: lock the IP after too many failed attempts.
    locked = is_login_locked(ip)
    if locked:
        raise APIError(429, "ACCOUNT_LOCKED", f"Çok fazla başarısız deneme. {locked} saniye sonra tekrar deneyin.")

    if not settings.supabase_url or not settings.supabase_anon_key:
        raise APIError(503, "AUTH_UNAVAILABLE", "Kimlik doğrulama servisi yapılandırılmadı")

    url = f"{settings.supabase_url}/auth/v1/token?grant_type=password"
    try:
        resp = httpx.post(
            url,
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
            json={"email": payload.email, "password": payload.password},
            timeout=15,
        )
    except httpx.HTTPError:
        raise APIError(503, "AUTH_UNAVAILABLE", "Kimlik doğrulama servisine ulaşılamadı")

    if resp.status_code != 200:
        record_failed_login(ip)
        raise APIError(401, "INVALID_CREDENTIALS", "E-posta veya şifre hatalı")

    clear_failed_logins(ip)  # successful login resets the counter
    session = resp.json()
    # Best-effort: stamp last_login_at.
    user_id = (session.get("user") or {}).get("id")
    if user_id:
        # CR-040: pre-company-context write → escalated (RLS-bypassing) session,
        # else under the app role the user row is invisible and the stamp no-ops.
        db = AdminSessionLocal()
        try:
            from app.models.user import User

            user = db.get(User, user_id)
            if user:
                user.last_login_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    return success(
        {
            "access_token": session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "expires_in": session.get("expires_in"),
            "token_type": session.get("token_type", "bearer"),
        }
    )


@router.post("/register")
def register(payload: RegisterRequest, claims: TokenClaims, db: Session = Depends(get_db)):
    """Provision the application company + director user for a freshly signed-up
    Supabase Auth user (Section 3.3 onboarding).

    Auth: a valid Supabase session token (the user has signed up but has no
    public.users row yet). Idempotent — if the user row already exists it is
    returned unchanged.
    """
    sub = claims.get("sub")
    try:
        uid = uuid.UUID(str(sub))
    except (ValueError, TypeError):
        raise APIError(401, "UNAUTHENTICATED", "Geçersiz kullanıcı kimliği")

    email = (payload.email or claims.get("email") or "").strip()
    if not email:
        raise APIError(422, "VALIDATION_ERROR", "E-posta gerekli", field="email")

    # Already provisioned? Return it (idempotent).
    existing = db.get(User, uid)
    if existing is not None:
        return success(UserOut.model_validate(existing).model_dump(mode="json"))

    # Guard against an email already attached to a different auth id.
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise APIError(422, "VALIDATION_ERROR", "Bu e-posta zaten kayıtlı", field="email")

    company = Company(
        name=payload.company_name,
        slug=_unique_slug(db, payload.company_name),
        default_currency="TRY",
        subscription_status="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(company)
    db.flush()

    # The first user of a new company is the director (Section 3.3).
    user = User(
        id=uid,
        company_id=company.id,
        full_name=payload.full_name or email.split("@")[0],
        email=email,
        role=ROLE_DIRECTOR,
        preferred_language="tr",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return success(UserOut.model_validate(user).model_dump(mode="json"))


@router.post("/logout")
def logout(user: CurrentUser):
    # Session revocation is handled by Supabase on the client; nothing to persist.
    return success({"message": "Oturum kapatıldı"})


@router.get("/me")
def me(user: CurrentUser, db: Session = Depends(get_db)):
    data = UserOut.model_validate(user).model_dump(mode="json")
    # CR-006-D: expose company name + logo so the sidebar can show the logo for
    # every role (the /settings/company endpoint is director-only).
    company = db.get(Company, user.company_id)
    data["company_name"] = company.name if company else None
    data["company_logo_url"] = company.logo_url if company else None
    return success(data)
