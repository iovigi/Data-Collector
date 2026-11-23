"""Redis client lifecycle and distributed rate limiter."""

from __future__ import annotations

import contextlib
import time
from typing import Any

import redis

from data_collector.config import Settings
from data_collector.domain.exceptions import RateLimitError, ServiceUnavailableError


class RateLimiter:
    """Fixed-window distributed rate limiter backed by Redis."""

    def __init__(self, redis_client: Any, fail_closed_mutations: bool = True) -> None:
        self._redis = redis_client
        self._fail_closed_mutations = fail_closed_mutations

    def check(
        self, key: str, limit: int, window_seconds: int = 60, *, is_mutation: bool = False
    ) -> None:
        """Increment counter and raise RateLimitError if exceeded."""
        bucket = int(time.time() // window_seconds)
        redis_key = f"rl:{key}:{bucket}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds + 5)
            count, _ = pipe.execute()
            if int(count) > limit:
                retry_after = window_seconds - (int(time.time()) % window_seconds)
                raise RateLimitError(
                    "Rate limit exceeded",
                    retry_after=max(1, retry_after),
                )
        except RateLimitError:
            raise
        except Exception as exc:
            if is_mutation and self._fail_closed_mutations:
                raise ServiceUnavailableError(
                    "Rate limiter unavailable for mutation",
                    retry_after=5,
                ) from exc


class RedisManager:
    """Manages Redis connection pool."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self.rate_limiter = RateLimiter(
            self._client,
            fail_closed_mutations=settings.rate_limit_fail_closed_mutations,
        )

    @property
    def client(self) -> Any:
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.close()
