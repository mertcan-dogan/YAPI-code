"""FastAPI dependencies: auth, current user, role gating (Section 3.2)."""
import logging
import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.responses import APIError
from app.security import TokenError, decode_token
from app.constants import (
    ROLE_DIRECTOR,
    ROLE_PROJECT_MANAGER,
    ROLE_FINANCE,
    ROLE_SITE_MANAGER,
)

logger = logging.getLogger("yapi.auth")


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        if settings.debug_auth:
            logger.warning("[auth] no/invalid Authorization header (value=%r) — frontend did not send a Bearer token", authorization)
        raise APIError(401, "UNAUTHENTICATED", "Kimlik doğrulama gerekli")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Validate the JWT and resolve the application user row.

    Unauthenticated requests return 401 (Section 12.1).
    """
    token = _extract_bearer(authorization)
    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise APIError(401, "UNAUTHENTICATED", str(exc))

    user_id = payload["sub"]
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        raise APIError(401, "UNAUTHENTICATED", "Geçersiz kullanıcı kimliği")

    user = db.execute(
        select(User).where(User.id == uid, User.is_deleted.is_(False))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        # Token verified but no matching app user row — common when the public.users
        # row was never created for this Supabase auth user (see /auth/me note).
        if settings.debug_auth:
            logger.warning("[auth] token valid (sub=%s) but no active users row found", user_id)
        raise APIError(401, "UNAUTHENTICATED", "Kullanıcı bulunamadı veya pasif")

    # Stash on request state for the audit middleware.
    request.state.user_id = str(user.id)
    request.state.company_id = str(user.company_id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_token_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Verify the JWT and return its claims WITHOUT requiring a public.users row.

    Used by the registration/provisioning endpoint, where the user has just
    signed up in Supabase Auth but has no application row yet.
    """
    token = _extract_bearer(authorization)
    try:
        return decode_token(token)
    except TokenError as exc:
        raise APIError(401, "UNAUTHENTICATED", str(exc))


TokenClaims = Annotated[dict, Depends(get_token_claims)]


def require_roles(*allowed: str):
    """Dependency factory enforcing that the current user holds one of the
    allowed roles, else 403 (Section 3.2)."""

    def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise APIError(403, "FORBIDDEN", "Bu işlem için yetkiniz yok")
        return user

    return _guard


# Convenience role guards
require_director = require_roles(ROLE_DIRECTOR)
require_director_or_pm = require_roles(ROLE_DIRECTOR, ROLE_PROJECT_MANAGER)
require_invoice_creator = require_roles(ROLE_DIRECTOR, ROLE_PROJECT_MANAGER, ROLE_FINANCE)
require_any = require_roles(
    ROLE_DIRECTOR, ROLE_PROJECT_MANAGER, ROLE_FINANCE, ROLE_SITE_MANAGER
)

# Role-typed dependency aliases — use as `user: DirectorUser` (no default value,
# avoids the "Depends in Annotated and default together" conflict).
DirectorUser = Annotated[User, Depends(require_director)]
DirectorOrPMUser = Annotated[User, Depends(require_director_or_pm)]
InvoiceCreatorUser = Annotated[User, Depends(require_invoice_creator)]
