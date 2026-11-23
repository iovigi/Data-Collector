"""Flask request-ID, authentication, rate limiting, and security headers middleware."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Flask, Response, current_app, g, request

from data_collector.container import Container
from data_collector.domain.exceptions import AuthenticationError, PayloadTooLargeError
from data_collector.domain.identities import Actor
from data_collector.infrastructure.logging import set_request_context


def get_container() -> Container:
    return current_app.extensions["container"]  # type: ignore[no-any-return]


def get_current_actor() -> Actor:
    actor = getattr(g, "actor", None)
    if actor is None:
        raise AuthenticationError("Authentication required")
    return actor  # type: ignore[no-any-return]


def register_middleware(app: Flask, container: Container) -> None:
    @app.before_request
    def _before_request() -> None:
        req_id = f"req_{uuid.uuid4().hex[:16]}"
        g.request_id = req_id
        set_request_context(req_id, req_id)

        # Enforce body size limit (higher for batch endpoint)
        max_bytes = container.settings.max_json_body_bytes
        if request.path.endswith("/records/batch"):
            max_bytes = container.settings.max_batch_bytes
        elif request.path.endswith("/imports"):
            max_bytes = container.settings.max_import_bytes
        if request.content_length is not None and request.content_length > max_bytes:
            raise PayloadTooLargeError(f"Request body exceeds {max_bytes} bytes")

    @app.after_request
    def _after_request(resp: Response) -> Response:
        req_id = getattr(g, "request_id", None)
        if req_id:
            resp.headers["X-Request-Id"] = req_id
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        # Everything is no-store unless a route explicitly opted in (hashed static assets).
        resp.headers["Cache-Control"] = getattr(g, "dc_cache_control", None) or "no-store"
        return resp


def require_auth(
    *, is_mutation: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Authenticate caller via Bearer JWT or X-API-Key, then apply rate limit."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            container = get_container()
            auth_header = request.headers.get("Authorization", "")
            api_key_header = request.headers.get("X-API-Key", "")

            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                actor = container.auth_service.authenticate_bearer(token)
            elif api_key_header:
                actor = container.auth_service.authenticate_api_key(api_key_header.strip())
            else:
                raise AuthenticationError("Missing Bearer token or X-API-Key")

            g.actor = actor
            limit = (
                container.settings.rate_limit_write_per_minute
                if is_mutation
                else container.settings.rate_limit_read_per_minute
            )
            container.redis.rate_limiter.check(
                f"actor:{actor.principal_id}:{'w' if is_mutation else 'r'}",
                limit,
                is_mutation=is_mutation,
            )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
