"""MCP actor resolution and OAuth 2.1 metadata helpers."""

from __future__ import annotations

import os
from contextvars import ContextVar

from data_collector.config import Settings
from data_collector.container import Container
from data_collector.domain.exceptions import AuthenticationError
from data_collector.domain.identities import Actor

_mcp_actor_var: ContextVar[Actor | None] = ContextVar("mcp_actor", default=None)


def set_mcp_actor(actor: Actor | None) -> None:
    _mcp_actor_var.set(actor)


def get_mcp_actor() -> Actor:
    actor = _mcp_actor_var.get()
    if actor is None:
        raise AuthenticationError("Unauthenticated MCP request")
    return actor


def resolve_stdio_actor(container: Container) -> Actor:
    """Resolve least-privileged local actor from DATA_COLLECTOR_API_KEY env var."""
    raw_key = os.environ.get("DATA_COLLECTOR_API_KEY", "").strip()
    if not raw_key:
        raise AuthenticationError(
            "DATA_COLLECTOR_API_KEY environment variable is required for stdio MCP"
        )
    return container.auth_service.authenticate_api_key(raw_key, is_mcp=True)


def resolve_http_actor(container: Container, headers: dict[str, str]) -> Actor:
    """Resolve actor from HTTP Authorization Bearer or X-API-Key header."""
    lowered = {k.lower(): v for k, v in headers.items()}
    auth = lowered.get("authorization", "")
    api_key = lowered.get("x-api-key", "")
    if auth.startswith("Bearer "):
        return container.auth_service.authenticate_bearer(auth[7:].strip(), is_mcp=True)
    if api_key:
        return container.auth_service.authenticate_api_key(api_key.strip(), is_mcp=True)
    raise AuthenticationError("Missing Bearer token or X-API-Key")


def protected_resource_metadata(settings: Settings) -> dict[str, object]:
    """RFC 9728 OAuth Protected Resource Metadata for MCP remote clients."""
    return {
        "resource": settings.mcp_public_url,
        "authorization_servers": [settings.auth_issuer.rstrip("/")],
        "scopes_supported": [
            "workspace:read",
            "collection:read",
            "records:read",
            "records:write",
            "records:delete",
            "jobs:read",
            "jobs:create",
            "export:read",
        ],
        "bearer_methods_supported": ["header"],
    }


def authorization_server_metadata(settings: Settings) -> dict[str, object]:
    """RFC 8414 OAuth 2.1 Authorization Server Metadata."""
    issuer = settings.auth_issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
    }
