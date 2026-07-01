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
from app.constants import INVITE_ACCEPTED, INVITE_PENDING, ROLE_DIRECTOR
from app.db import AdminSessionLocal, get_db
from app.deps import CurrentUser, TokenClaims
from app.models.company import Company
from app.models.invite import Invite
from app.models.user import User
from app.responses import APIError, success
from app.schemas.invite import InviteAccept
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


def _invite_is_expired(invite: Invite) -> bool:
    exp = invite.expires_at
    if exp is None:
        return False
    # SQLite returns naive datetimes; treat them as UTC so the comparison is safe.
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


def _load_acceptable_invite(db: Session, token: str) -> Invite:
    """Resolve a token to a still-acceptable (pending, unexpired) invite or 404.

    Deliberately returns the same 404 for unknown / revoked / accepted / expired
    so a token holder cannot probe which state a token is in.
    """
    invite = db.execute(
        select(Invite).where(Invite.token == token, Invite.is_deleted.is_(False))
    ).scalar_one_or_none()
    if invite is None or invite.status != INVITE_PENDING or _invite_is_expired(invite):
        raise APIError(404, "NOT_FOUND", "Davet bulunamadı veya süresi dolmuş")
    return invite


@router.get("/invite/{token}")
def get_invite(token: str):
    """Public: preview an invite (company name + email + role) so the accept page
    can render. Runs on the ESCALATED (RLS-bypassing) session — the visitor has no
    company context, so the request session could never read the invite row."""
    db = AdminSessionLocal()
    try:
        invite = _load_acceptable_invite(db, token)
        company = db.get(Company, invite.company_id)
        return success(
            {
                "company_name": company.name if company else None,
                "email": invite.email,
                "role": invite.role,
            }
        )
    finally:
        db.close()


@router.post("/invite/{token}/accept")
def accept_invite(token: str, payload: InviteAccept, claims: TokenClaims):
    """Accept an invite: create the caller's public.users row attached to the
    INVITING company with the invited role, then mark the invite accepted.

    Auth: a valid Supabase session token (the user has just signed up / signed in
    but has no public.users row yet). ESCALATED session — no company context
    exists until this very call writes it (mirrors /auth/register and
    get_current_user). The new user's company_id is what later derives the
    app.current_company GUC on every subsequent request.
    """
    sub = claims.get("sub")
    try:
        uid = uuid.UUID(str(sub))
    except (ValueError, TypeError):
        raise APIError(401, "UNAUTHENTICATED", "Geçersiz kullanıcı kimliği")
    token_email = (claims.get("email") or "").strip().lower()

    db = AdminSessionLocal()
    try:
        invite = _load_acceptable_invite(db, token)
        invite_email = invite.email.strip().lower()

        # The signed-in identity must be the invited address — otherwise anyone
        # holding the link could join under a different account (CR-041 security).
        if token_email and token_email != invite_email:
            raise APIError(403, "FORBIDDEN", "Bu davet farklı bir e-posta adresi için gönderildi")

        # A user already attached to a company cannot accept another company's
        # invite — multi-company membership is out of scope (human decision).
        if db.get(User, uid) is not None:
            raise APIError(422, "VALIDATION_ERROR", "Zaten bir şirkete kayıtlısınız")

        # users.email is globally unique: guard an email tied to a different auth id.
        if db.execute(select(User).where(User.email == invite_email)).scalar_one_or_none() is not None:
            raise APIError(422, "VALIDATION_ERROR", "Bu e-posta zaten kayıtlı", field="email")

        user = User(
            id=uid,
            company_id=invite.company_id,
            full_name=(payload.full_name or "").strip() or invite_email.split("@")[0],
            email=invite_email,
            role=invite.role,
            preferred_language="tr",
            is_active=True,
        )
        db.add(user)
        invite.status = INVITE_ACCEPTED
        invite.accepted_by = uid
        invite.accepted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        return success(UserOut.model_validate(user).model_dump(mode="json"))
    finally:
        db.close()


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
