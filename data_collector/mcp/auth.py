"""MCP actor resolution and OAuth 2.1 metadata helpers."""

from __future__ import annotations

import os
from contextvars import ContextVar, Token

from data_collector.config import Settings
from data_collector.container import Container
from data_collector.domain.exceptions import AuthenticationError
from data_collector.domain.identities import Actor
from data_collector.infrastructure.oauth import DEFAULT_CLIENT_SCOPES, MCP_OAUTH_SCOPES

_mcp_actor_var: ContextVar[Actor | None] = ContextVar("mcp_actor", default=None)


def set_mcp_actor(actor: Actor | None) -> Token[Actor | None]:
    return _mcp_actor_var.set(actor)


def reset_mcp_actor(token: Token[Actor | None]) -> None:
    _mcp_actor_var.reset(token)


def _actor_from_sdk_request() -> Actor | None:
    """Actor attached by MCPAuthASGIMiddleware to the HTTP request that carried this message.

    The MCP SDK sets ``request_ctx`` for every JSON-RPC message it handles, including the
    originating Starlette ``Request``. This is per-message and does not depend on how the
    SDK schedules tasks (stateful vs stateless), so it is preferred over the contextvar.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except ImportError:  # pragma: no cover - SDK layout change
        return None
    ctx = request_ctx.get(None)
    request = getattr(ctx, "request", None)
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        candidate = scope.get("dc_actor")
        if isinstance(candidate, Actor):
            return candidate
    return None


def get_mcp_actor() -> Actor:
    actor = _actor_from_sdk_request() or _mcp_actor_var.get()
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


MCP_TOKEN_PREFIX = "dcp_"  # noqa: S105 - public token prefix, not a secret
WORKSPACE_KEY_PREFIX = "dc_"


def resolve_http_actor(container: Container, headers: dict[str, str]) -> Actor:
    """Resolve the MCP caller.

    - `Authorization: Bearer dcp_...`: MCP personal access token (header-based clients
      such as Claude Code or ChatGPT developer mode without a browser).
    - `Authorization: Bearer <JWT>`: OAuth 2.1 access token (RS256/JWKS, aud=MCP URL).
    - `X-API-Key`: legacy; workspace API keys and MCP tokens.
    A workspace API key sent as Bearer gets a precise error instead of "wrong audience".
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    auth = lowered.get("authorization", "")
    api_key = lowered.get("x-api-key", "")
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
        if token.startswith(MCP_TOKEN_PREFIX):
            return container.auth_service.authenticate_api_key(
                token, is_mcp=True, require_mcp_token=True
            )
        if token.startswith(WORKSPACE_KEY_PREFIX) and "." in token and token.count(".") == 1:
            raise AuthenticationError(
                "Workspace API keys are not MCP tokens. Create an MCP access token in the "
                "admin (MCP page) or connect with OAuth."
            )
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
        "scopes_supported": list(MCP_OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "Data Collector",
    }


def www_authenticate_challenge(settings: Settings) -> str:
    """401 challenge pointing at RFC 9728 metadata, hinting read-only scopes first."""
    base = settings.mcp_public_url.removesuffix("/mcp").rstrip("/")
    prm_url = f"{base}/.well-known/oauth-protected-resource"
    scope = " ".join(DEFAULT_CLIENT_SCOPES)
    return f'Bearer resource_metadata="{prm_url}", scope="{scope}"'


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
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": list(MCP_OAUTH_SCOPES),
        }
    issuer = settings.auth_issuer.rstrip("/")
    return {
        "issuer": issuer,
        "jwks_uri": settings.oauth_jwks_url or f"{issuer}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }
