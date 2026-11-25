"""Session-bound double-submit CSRF tokens and Origin/Referer verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit


def _sid_digest(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def create_csrf_token(secret: str, sid: str) -> str:
    """``nonce.HMAC(secret, "csrf|" + sha256(sid) + "|" + nonce)`` - bound to one session."""
    nonce = secrets.token_hex(16)
    mac = hmac.new(
        secret.encode("utf-8"),
        f"csrf|{_sid_digest(sid)}|{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{mac}"


def verify_csrf_token(
    secret: str, sid: str, cookie_val: str | None, header_val: str | None
) -> bool:
    if not sid or not cookie_val or not header_val:
        return False
    if not hmac.compare_digest(cookie_val.encode("utf-8"), header_val.encode("utf-8")):
        return False
    parts = header_val.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    nonce, mac = parts
    expected = hmac.new(
        secret.encode("utf-8"),
        f"csrf|{_sid_digest(sid)}|{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(mac.encode("utf-8"), expected.encode("utf-8"))


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower()


def is_trusted_origin(
    origin: str | None, referer: str | None, allowed_origins: Iterable[str]
) -> bool:
    """State-changing browser requests must come from one of the configured origins.

    ``Origin`` is checked when present; otherwise ``Referer``. A request with neither is
    rejected (browsers always send ``Origin`` on cross-site and same-site POST fetches).
    """
    allowed = {o.strip().rstrip("/").lower() for o in allowed_origins if o.strip()}
    if origin:
        return origin.strip().rstrip("/").lower() in allowed
    if referer:
        return _origin_of(referer) in allowed
    return False


def sanitize_return_path(raw: str | None, fallback: str = "/") -> str:
    if not raw or not raw.startswith("/") or raw.startswith("//") or "://" in raw or "\\" in raw:
        return fallback
    return raw
