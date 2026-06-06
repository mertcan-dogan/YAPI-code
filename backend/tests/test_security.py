"""JWT verification tests — legacy HS256 + new-format tolerance."""
import time

import jwt
import pytest

from app.config import settings
from app.security import TokenError, decode_token

SECRET = settings.jwt_secret


def _hs256(claims: dict) -> str:
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_valid_hs256_token_decodes():
    tok = _hs256({"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 3600})
    payload = decode_token(tok)
    assert payload["sub"] == "user-123"


def test_audience_as_list_is_accepted():
    tok = _hs256({"sub": "u", "aud": ["authenticated"], "exp": int(time.time()) + 3600})
    assert decode_token(tok)["sub"] == "u"


def test_missing_audience_is_tolerated():
    # New-format tokens may omit/alter aud; we must not hard-fail on it.
    tok = _hs256({"sub": "u", "exp": int(time.time()) + 3600})
    assert decode_token(tok)["sub"] == "u"


def test_wrong_audience_rejected():
    tok = _hs256({"sub": "u", "aud": "anon", "exp": int(time.time()) + 3600})
    with pytest.raises(TokenError):
        decode_token(tok)


def test_expired_token_rejected():
    tok = _hs256({"sub": "u", "aud": "authenticated", "exp": int(time.time()) - 10})
    with pytest.raises(TokenError):
        decode_token(tok)


def test_token_without_sub_rejected():
    tok = _hs256({"aud": "authenticated", "exp": int(time.time()) + 3600})
    with pytest.raises(TokenError):
        decode_token(tok)


def test_unsupported_algorithm_rejected():
    # "none" alg / algorithm confusion must be refused.
    unsigned = jwt.encode({"sub": "u"}, key="", algorithm="none")
    with pytest.raises(TokenError):
        decode_token(unsigned)


def test_garbage_token_rejected():
    with pytest.raises(TokenError):
        decode_token("not-a-jwt")


def _b64url(obj) -> str:
    import base64
    import json

    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def test_asymmetric_token_routes_to_jwks(monkeypatch):
    """An ES256/RS256 token must be routed to JWKS verification, not HS256."""
    import app.security as sec

    called = {"jwks": False}

    class FakeClient:
        def get_signing_key_from_jwt(self, token):
            called["jwks"] = True
            raise jwt.PyJWKClientError("no matching key")

    monkeypatch.setattr(sec, "_get_jwks_client", lambda: FakeClient())
    # Hand-craft a token whose header advertises RS256 so decode_token takes the
    # asymmetric branch (the signature itself is irrelevant for this routing test).
    tok = f"{_b64url({'alg': 'RS256', 'typ': 'JWT', 'kid': 'k1'})}.{_b64url({'sub': 'u', 'aud': 'authenticated'})}.AAAA"
    with pytest.raises(TokenError):
        decode_token(tok)
    assert called["jwks"] is True
