"""Token and password primitives."""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

TOKEN_PREFIX = "sbh_"  # noqa: S105

_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id, RFC 9106 low-memory profile
_DUMMY_HASH = _hasher.hash("timing-equalizer")


def hash_token(token: str) -> str:
    """SHA-256 hex. Fine for 256-bit random secrets (no need for a slow KDF)."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_ingest_token() -> tuple[str, str, str]:
    """(plaintext, sha256, display prefix)."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_token(plaintext), plaintext[:8]


def new_session_secret() -> tuple[str, str]:
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_token(plaintext)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Takes the same time whether or not the user exists (stored_hash=None)."""
    try:
        ok = _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
