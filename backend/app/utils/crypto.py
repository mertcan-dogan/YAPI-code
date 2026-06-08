"""Application-layer field encryption for sensitive data at rest (CR-002-I 10.3).

Uses Fernet (AES-128-CBC + HMAC) keyed by ENCRYPTION_KEY. Encryption happens
ONLY in the backend; the key never leaves the server.

NOTE: the live financial columns (contract_value_try, margin inputs, …) are
deliberately NOT encrypted here because they are aggregated in real time by the
calculation engine and by SQL — encrypting them would break those computations
and RLS. This utility provides the capability for genuinely sensitive,
non-computed fields (e.g. notes, contact details) and future use.
"""
import base64
import hashlib

from app.config import settings


class EncryptionUnavailable(Exception):
    pass


def _fernet():
    from cryptography.fernet import Fernet

    key = settings.encryption_key
    if not key:
        raise EncryptionUnavailable("ENCRYPTION_KEY tanımlı değil")
    # Accept any passphrase: derive a 32-byte urlsafe base64 key from it.
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str | None) -> str | None:
    if token is None:
        return None
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
