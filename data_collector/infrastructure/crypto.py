"""Cryptographic helpers: Argon2id passwords, API key hashing, signed intent tokens."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Verify password against Argon2id or legacy bcrypt hash.

    Returns (is_valid, needs_rehash).
    """
    if stored_hash.startswith("$argon2"):
        try:
            valid = bool(_ph.verify(stored_hash, password))
            return valid, _ph.check_needs_rehash(stored_hash) if valid else False
        except VerifyMismatchError:
            return False, False
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            valid = bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
            return valid, valid  # migrate legacy bcrypt -> argon2id on successful login
        except ValueError:
            return False, False
    return False, False


def generate_api_key() -> tuple[str, str, str]:
    """Generate a prefixed API key: (plaintext_key, prefix, sha256_hash)."""
    prefix = f"dc_{secrets.token_hex(4)}"
    secret = secrets.token_urlsafe(32)
    plaintext = f"{prefix}.{secret}"
    key_hash = hash_token(plaintext)
    return plaintext, prefix, key_hash


def hash_token(token: str) -> str:
    """Return hex SHA-256 digest of a high-entropy token/key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, expected_hash: str) -> bool:
    """Constant-time verification of token hash."""
    actual = hash_token(token)
    return hmac.compare_digest(actual, expected_hash)


def sign_intent_token(payload: dict[str, Any], secret: str, ttl_seconds: int = 300) -> str:
    """Create a short-lived HMAC-SHA256 signed intent token (e.g. for MCP two-stage delete)."""
    data = {
        **payload,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
        "jti": secrets.token_hex(8),
    }
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64 = urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_intent_token(token: str, secret: str) -> dict[str, Any] | None:
    """Verify and decode a signed intent token; returns None if invalid or expired."""
    try:
        b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected_sig = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    padded = b64 + "=" * (-len(b64) % 4)
    try:
        data: dict[str, Any] = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    return data
