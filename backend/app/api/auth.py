"""Auth router (Section 2.5, 3.1). Authentication is delegated to Supabase Auth.

/auth/login proxies the password grant to Supabase (the only way the backend
ever sees a password — it is never stored). The frontend may alternatively use
the Supabase JS client directly; either way the backend only ever validates the
resulting JWT.
"""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from app.config import settings
from app.db import SessionLocal
from app.deps import CurrentUser
from app.responses import APIError, success
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: LoginRequest):
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
        raise APIError(401, "INVALID_CREDENTIALS", "E-posta veya şifre hatalı")

    session = resp.json()
    # Best-effort: stamp last_login_at.
    user_id = (session.get("user") or {}).get("id")
    if user_id:
        db = SessionLocal()
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


@router.post("/logout")
def logout(user: CurrentUser):
    # Session revocation is handled by Supabase on the client; nothing to persist.
    return success({"message": "Oturum kapatıldı"})


@router.get("/me")
def me(user: CurrentUser):
    return success(UserOut.model_validate(user).model_dump(mode="json"))
