"""Server-side browser sessions in Redis with cross-process refresh locking.

* The browser only ever holds an opaque, random 256-bit session ID in an HttpOnly cookie.
  Access and refresh tokens stay in Redis and never reach browser JavaScript.
* Redis keys use ``sha256(session_id)``; a Redis dump does not reveal usable cookies.
* Refresh-token rotation is serialised per session with a Redis lock, so concurrent
  requests in different IIS FastCGI processes cannot replay a rotated refresh token
  (which the API treats as theft and answers by revoking the whole token family).
* Redis unavailable -> ``ServiceUnavailableError`` (503). There is no in-memory fallback.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import time
from typing import Any

from data_collector.domain.exceptions import AuthenticationError, ServiceUnavailableError

_SESSION_PREFIX = "dc:web:sess:"
_LOCK_PREFIX = "dc:web:lock:"
REFRESH_MARGIN_SECONDS = 15


def _key(sid: str) -> str:
    return _SESSION_PREFIX + hashlib.sha256(sid.encode("utf-8")).hexdigest()


def _lock_key(sid: str) -> str:
    return _LOCK_PREFIX + hashlib.sha256(sid.encode("utf-8")).hexdigest()


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


class WebSessionStore:
    def __init__(self, redis_client: Any, ttl_seconds: int) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _unavailable(self, exc: Exception) -> ServiceUnavailableError:
        return ServiceUnavailableError("Session store unavailable", retry_after=5)

    def create(self, tokens: dict[str, Any], *, user_id: str, email: str | None) -> str:
        sid = new_session_id()
        now = int(time.time())
        self._write(
            sid,
            {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "expires_at": now + int(tokens.get("expires_in", 900)),
                "user_id": user_id,
                "email": email,
                "created_at": now,
            },
        )
        return sid

    def _write(self, sid: str, data: dict[str, Any]) -> None:
        try:
            self._redis.set(_key(sid), json.dumps(data), ex=self._ttl)
        except Exception as exc:
            raise self._unavailable(exc) from exc

    def get(self, sid: str) -> dict[str, Any] | None:
        if not sid:
            return None
        try:
            raw = self._redis.get(_key(sid))
        except Exception as exc:
            raise self._unavailable(exc) from exc
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def delete(self, sid: str) -> None:
        if not sid:
            return
        try:
            self._redis.delete(_key(sid))
        except Exception as exc:
            raise self._unavailable(exc) from exc

    def refresh(self, sid: str, auth_service: Any, *, force: bool = False) -> dict[str, Any] | None:
        """Rotate tokens once per session even under concurrent callers.

        Returns the (possibly already refreshed) session, or None if the session is gone or
        the refresh token was rejected (the session is then deleted).
        """
        try:
            lock = self._redis.lock(_lock_key(sid), timeout=15, blocking_timeout=10)
            acquired = lock.acquire()
        except Exception as exc:
            raise self._unavailable(exc) from exc
        if not acquired:
            raise ServiceUnavailableError("Session refresh is busy", retry_after=2)
        try:
            current = self.get(sid)
            if current is None:
                return None
            fresh_enough = int(current.get("expires_at", 0)) - REFRESH_MARGIN_SECONDS > time.time()
            if fresh_enough and not force:
                return current  # another request already rotated the tokens
            try:
                tokens = auth_service.refresh(str(current.get("refresh_token", "")))
            except AuthenticationError:
                self.delete(sid)
                return None
            current.update(
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                expires_at=int(time.time()) + int(tokens.get("expires_in", 900)),
            )
            self._write(sid, current)
            return current
        finally:
            # The lock may have expired; nothing to undo.
            with contextlib.suppress(Exception):
                lock.release()

    @staticmethod
    def needs_refresh(session: dict[str, Any]) -> bool:
        return int(session.get("expires_at", 0)) - REFRESH_MARGIN_SECONDS <= time.time()
