"""MCP actor resolution and OAuth 2.1 metadata helpers."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token

from data_collector.config import Settings
from data_collector.container import Container
from data_collector.domain.exceptions import AuthenticationError
from data_collector.domain.identities import Actor

_mcp_actor_var: ContextVar[Actor | None] = ContextVar("mcp_actor", default=None)


def set_mcp_actor(actor: Actor | None) -> Token[Actor | None]:
    return _mcp_actor_var.set(actor)


def reset_mcp_actor(token: Token[Actor | None]) -> None:
    _mcp_actor_var.reset(token)


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
    """Resolve actor from OAuth 2.1 Bearer token (RS256/JWKS) or X-API-Key."""
    lowered = {k.lower(): v for k, v in headers.items()}
    auth = lowered.get("authorization", "")
    api_key = lowered.get("x-api-key", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return container.oauth_service.verify_bearer_token(token, is_mcp=True)
    if api_key:
        return container.auth_service.authenticate_api_key(api_key.strip(), is_mcp=True)
    raise AuthenticationError("Missing OAuth Bearer token or X-API-Key")


def protected_resource_metadata(settings: Settings) -> dict[str, object]:
    """RFC 9728 OAuth Protected Resource Metadata for MCP remote clients."""
    if settings.oauth_mode == "builtin":
        base = settings.mcp_public_url.removesuffix("/mcp").rstrip("/")
        auth_servers = [base]
    else:
        auth_servers = [settings.auth_issuer.rstrip("/")]
    return {
        "resource": settings.mcp_public_url,
        "authorization_servers": auth_servers,
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
    """RFC 8414 OAuth 2.1 Authorization Server Metadata matching active mode."""
    if settings.oauth_mode == "builtin":
        base = settings.mcp_public_url.removesuffix("/mcp").rstrip("/")
        issuer = settings.auth_issuer.rstrip("/")
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "registration_endpoint": f"{base}/oauth/register",
            "jwks_uri": f"{base}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    issuer = settings.auth_issuer.rstrip("/")
    return {
        "issuer": issuer,
        "jwks_uri": settings.oauth_jwks_url or f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }
