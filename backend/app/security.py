"""JWT verification for Supabase Auth tokens (Section 3.1, 8.1).

Supports both Supabase token-signing schemes:

* **Legacy HS256** — access tokens signed with the project's shared JWT secret
  (`JWT_SECRET`). Verified symmetrically.
* **New asymmetric signing keys (ES256 / RS256)** — introduced alongside the new
  `sb_publishable_` / `sb_secret_` API keys. Access tokens are signed with a
  rotating key pair and verified against the project's public JWKS endpoint
  (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`). No shared secret is needed.

The algorithm in the token header selects the path automatically, so the same
backend works for projects on either scheme (and during migration between them).

Note: the `sb_publishable_` / `sb_secret_` strings are *API keys*, not session
tokens — they never reach this function. What arrives in the `Authorization`
header is always the per-user access-token JWT.
"""
import logging
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger("yapi.auth")

# Algorithms we accept. HS256 = legacy shared secret; the rest = asymmetric JWKS.
_ASYMMETRIC_ALGS = {"ES256", "RS256", "ES384", "RS384", "ES512", "RS512"}
_ALLOWED_ALGS = {"HS256", *_ASYMMETRIC_ALGS}

_jwks_client: PyJWKClient | None = None


class TokenError(Exception):
    pass


def _jwks_url() -> str | None:
    if settings.supabase_jwks_url:
        return settings.supabase_jwks_url
    if settings.supabase_url:
        return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return None


def _get_jwks_client() -> PyJWKClient:
    """Lazily build a cached JWKS client (fetches & caches the public keys)."""
    global _jwks_client
    if _jwks_client is None:
        url = _jwks_url()
        if not url:
            raise TokenError("JWKS uç noktası yapılandırılmadı")
        _jwks_client = PyJWKClient(url, cache_keys=True)
    return _jwks_client


def _check_audience(payload: dict[str, Any]) -> None:
    """Supabase tokens carry aud 'authenticated'. Tolerate string or list and
    allow projects that omit/customise it rather than hard-failing."""
    aud = payload.get("aud")
    if aud is None:
        return
    auds = aud if isinstance(aud, list) else [aud]
    if "authenticated" not in auds:
        raise TokenError("Geçersiz oturum hedefi")


def decode_token(token: str) -> dict[str, Any]:
    """Verify a Supabase-issued access-token JWT and return its claims."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise TokenError("Geçersiz oturum belirteci") from exc

    alg = header.get("alg", "HS256")
    if alg not in _ALLOWED_ALGS:
        raise TokenError(f"Desteklenmeyen imza algoritması: {alg}")

    # We verify the audience manually (tolerant), so disable strict aud checking.
    # leeway absorbs minor clock skew between Supabase and this server.
    options = {"verify_aud": False}

    try:
        if alg == "HS256":
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=["HS256"], options=options, leeway=10
            )
        else:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token, signing_key.key, algorithms=list(_ASYMMETRIC_ALGS), options=options, leeway=10
            )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Oturum süresi doldu") from exc
    except TokenError:
        raise
    except jwt.PyJWKClientError as exc:
        logger.warning("JWKS doğrulama hatası: %s", exc)
        raise TokenError("Oturum doğrulanamadı") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Geçersiz oturum belirteci") from exc

    _check_audience(payload)

    if "sub" not in payload:
        raise TokenError("Belirteç kullanıcı kimliği içermiyor")
    return payload
