"""JWT verification for Supabase Auth tokens (Section 3.1, 8.1).

Supports both Supabase token-signing schemes, auto-selected by the token header:

* **Legacy HS256** — signed with the shared project JWT secret (`JWT_SECRET`).
* **Asymmetric ES256 / RS256** — the new Supabase signing keys (the
  `sb_publishable_` / `sb_secret_` era). Verified against the project's public
  JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`).

The `sb_publishable_` / `sb_secret_` strings are *API keys*, never session
tokens — they do not reach this module. What arrives in `Authorization` is the
per-user access-token JWT.

Set DEBUG_AUTH=1 (default outside production) to log the algorithm, kid, JWKS
URL and the exact failure reason for every rejected token.
"""
import json
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

# Is PyJWT able to do asymmetric crypto? (requires the `cryptography` package)
try:  # pragma: no cover - import-time capability probe
    import cryptography  # noqa: F401

    _CRYPTO_AVAILABLE = True
except Exception:  # pragma: no cover
    _CRYPTO_AVAILABLE = False


class TokenError(Exception):
    pass


def _dbg(msg: str, *args) -> None:
    if settings.debug_auth:
        logger.warning("[auth] " + msg, *args)


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
        _dbg("creating JWKS client url=%s", url)
        _jwks_client = PyJWKClient(url, cache_keys=True)
    return _jwks_client


def reset_jwks_client() -> None:
    """Drop the cached JWKS client (used after key rotation or in tests)."""
    global _jwks_client
    _jwks_client = None


def _check_audience(payload: dict[str, Any]) -> None:
    """Supabase tokens carry aud 'authenticated'. Tolerate string or list and
    allow projects that omit/customise it rather than hard-failing."""
    aud = payload.get("aud")
    if aud is None:
        return
    auds = aud if isinstance(aud, list) else [aud]
    if "authenticated" not in auds:
        raise TokenError("Geçersiz oturum hedefi")


def _unverified(token: str) -> tuple[dict, dict]:
    header = jwt.get_unverified_header(token)
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        payload = {}
    return header, payload


def decode_token(token: str) -> dict[str, Any]:
    """Verify a Supabase-issued access-token JWT and return its claims."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        _dbg("malformed token, cannot read header: %s", exc)
        raise TokenError("Geçersiz oturum belirteci") from exc

    alg = header.get("alg", "HS256")
    kid = header.get("kid")
    _dbg("verifying token alg=%s kid=%s crypto_available=%s", alg, kid, _CRYPTO_AVAILABLE)

    if alg not in _ALLOWED_ALGS:
        _dbg("rejecting unsupported alg=%s", alg)
        raise TokenError(f"Desteklenmeyen imza algoritması: {alg}")

    if alg in _ASYMMETRIC_ALGS and not _CRYPTO_AVAILABLE:
        # PyJWT cannot verify ES/RS tokens without the `cryptography` package.
        _dbg("cryptography package missing — cannot verify %s tokens", alg)
        raise TokenError("Sunucu asimetrik imzaları doğrulayamıyor (cryptography eksik)")

    # We verify audience manually (tolerant); leeway absorbs minor clock skew.
    options = {"verify_aud": False}

    try:
        if alg == "HS256":
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=["HS256"], options=options, leeway=10
            )
        else:
            url = _jwks_url()
            _dbg("using JWKS url=%s", url)
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token, signing_key.key, algorithms=list(_ASYMMETRIC_ALGS), options=options, leeway=10
            )
    except jwt.ExpiredSignatureError as exc:
        _dbg("token EXPIRED: %s", exc)
        raise TokenError("Oturum süresi doldu") from exc
    except TokenError:
        raise
    except jwt.PyJWKClientError as exc:
        # kid not found in JWKS, JWKS unreachable, etc.
        _dbg("JWKS verification FAILED (%s): %s | url=%s kid=%s",
             type(exc).__name__, exc, _jwks_url(), kid)
        raise TokenError("Oturum doğrulanamadı (JWKS)") from exc
    except Exception as exc:  # broad: also catches InvalidAlgorithmError, InvalidKeyError
        try:
            _, up = _unverified(token)
        except Exception:
            up = {}
        _dbg("verification FAILED (%s): %s | alg=%s kid=%s aud=%s iss=%s",
             type(exc).__name__, exc, alg, kid, up.get("aud"), up.get("iss"))
        raise TokenError("Geçersiz oturum belirteci") from exc

    _check_audience(payload)

    if "sub" not in payload:
        raise TokenError("Belirteç kullanıcı kimliği içermiyor")

    _dbg("token OK sub=%s alg=%s", payload.get("sub"), alg)
    return payload


# Alias — some call sites refer to this as verify_token.
verify_token = decode_token
