"""Isolated auxiliary cache and distributed lock helper (Redis-backed, fail-safe)."""

from __future__ import annotations

import json
import secrets
from typing import Any

_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class AuxiliaryCache:
    """Namespaced auxiliary cache for derived counts and search checkpoints."""

    def __init__(self, redis_client: Any | None = None, *, namespace: str = "dc") -> None:
        self._client = redis_client
        self._namespace = namespace

    def count_key(self, workspace_id: str, project_id: str, collection_id: str, kind: str) -> str:
        return f"{self._namespace}:counts:v1:{workspace_id}:{project_id}:{collection_id}:{kind}"

    def count_lock_key(
        self, workspace_id: str, project_id: str, collection_id: str, kind: str
    ) -> str:
        return (
            f"{self._namespace}:counts:lock:v1:{workspace_id}:{project_id}:{collection_id}:{kind}"
        )

    def get_json(self, key: str) -> dict[str, Any] | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            val = json.loads(raw)
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    def get_many_json(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys or self._client is None:
            return [None for _ in keys]
        try:
            rows = self._client.mget(keys)
        except Exception:
            return [None for _ in keys]
        out: list[dict[str, Any] | None] = []
        for raw in rows:
            if not raw:
                out.append(None)
                continue
            try:
                text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                val = json.loads(text)
                out.append(val if isinstance(val, dict) else None)
            except Exception:
                out.append(None)
        return out

    def set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> bool:
        if self._client is None:
            return False
        try:
            self._client.set(
                key,
                json.dumps(payload, separators=(",", ":")),
                ex=max(1, ttl_seconds),
            )
            return True
        except Exception:
            return False

    def delete(self, *keys: str) -> None:
        if self._client is None or not keys:
            return
        try:
            self._client.delete(*keys)
        except Exception:
            return

    def acquire_lock(self, key: str, ttl_seconds: int = 15) -> str | None:
        if self._client is None:
            return secrets.token_hex(8)
        token = secrets.token_hex(16)
        try:
            acquired = self._client.set(key, token, nx=True, ex=max(1, ttl_seconds))
            return token if acquired else None
        except Exception:
            return None

    def release_lock(self, key: str, token: str) -> None:
        if self._client is None or not token:
            return
        try:
            self._client.eval(_RELEASE_LUA, 1, key, token)
        except Exception:
            return
