"""JWT verification for Supabase Auth tokens (Section 3.1, 8.1)."""
from typing import Any

import jwt

from app.config import settings


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict[str, Any]:
    """Verify a Supabase-issued JWT (HS256, signed with the project JWT secret).

    Supabase tokens carry audience 'authenticated' and the user id in 'sub'.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="authenticated",
            options={"verify_aud": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Oturum süresi doldu") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Geçersiz oturum belirteci") from exc

    if "sub" not in payload:
        raise TokenError("Belirteç kullanıcı kimliği içermiyor")
    return payload
