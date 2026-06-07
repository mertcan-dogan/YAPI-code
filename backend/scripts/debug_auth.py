"""Standalone auth diagnostic.

Pinpoints exactly where Supabase token verification fails — run it with a real
access token copied from the browser.

Usage (from the backend/ directory, with .env populated):

    python scripts/debug_auth.py "<paste access_token here>"

  or set it via env:

    TOKEN=eyJ... python scripts/debug_auth.py

How to get the token in the browser console (while logged in):

    (await window.supabase?.auth?.getSession())?.data?.session?.access_token
    // or, if not exposed, from DevTools > Application > Local Storage >
    //   the `sb-<ref>-auth-token` entry > access_token

It prints: the token header (alg/kid), claims (sub/aud/iss/exp), the JWKS URL,
the kids published by Supabase, whether `cryptography` is installed, and the
exact verification result/error.
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import jwt  # noqa: E402

from app.config import settings  # noqa: E402
from app import security  # noqa: E402


def b(label: str, value) -> None:
    print(f"  {label:<22} {value}")


def main() -> None:
    token = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("TOKEN", "")).strip()
    if not token:
        print("ERROR: pass the access token as an argument or TOKEN env var.")
        sys.exit(2)

    print("\n=== CONFIG ===")
    b("SUPABASE_URL", settings.supabase_url or "(empty)")
    b("JWKS URL", security._jwks_url() or "(none)")
    b("JWT_SECRET set", bool(settings.jwt_secret and settings.jwt_secret != "dev-insecure-secret-change-me"))
    b("cryptography avail", security._CRYPTO_AVAILABLE)

    print("\n=== TOKEN HEADER ===")
    try:
        header = jwt.get_unverified_header(token)
        b("alg", header.get("alg"))
        b("kid", header.get("kid"))
        b("typ", header.get("typ"))
    except Exception as exc:  # noqa: BLE001
        print(f"  Could not parse header: {exc}")
        sys.exit(1)

    print("\n=== TOKEN CLAIMS (unverified) ===")
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        for key in ("sub", "aud", "iss", "exp", "role", "email"):
            if key in claims:
                b(key, claims[key])
    except Exception as exc:  # noqa: BLE001
        print(f"  Could not parse claims: {exc}")

    # Show kids published by the JWKS endpoint, to compare against the token kid.
    url = security._jwks_url()
    if url and header.get("alg") in security._ASYMMETRIC_ALGS:
        print("\n=== JWKS ENDPOINT ===")
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
                jwks = json.loads(resp.read())
            kids = [(k.get("kid"), k.get("alg"), k.get("kty"), k.get("crv")) for k in jwks.get("keys", [])]
            b("keys found", len(kids))
            for kid, alg, kty, crv in kids:
                print(f"      kid={kid} alg={alg} kty={kty} crv={crv}")
            token_kid = header.get("kid")
            if token_kid and token_kid not in [k[0] for k in kids]:
                print(f"  [WARN] token kid={token_kid} NOT present in JWKS — key rotation/mismatch")
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] Could not fetch JWKS: {type(exc).__name__}: {exc}")

    print("\n=== VERIFICATION (via app.security.decode_token) ===")
    security.reset_jwks_client()
    try:
        payload = security.decode_token(token)
        print("  [OK] SUCCESS — token verified.")
        b("sub", payload.get("sub"))
        print("\n  Next: confirm a row exists in public.users with id =", payload.get("sub"))
        print("  (a valid token with no matching users row also yields 401 on /auth/me).")
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] FAILED — {type(exc).__name__}: {exc}")
        print("\n  Full traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
