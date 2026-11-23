"""Remote HTTPS Streamable HTTP MCP server (`dc-mcp-http`) with OAuth 2.1 metadata."""

from __future__ import annotations

from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from data_collector.config import Settings, get_settings
from data_collector.container import Container, build_container
from data_collector.domain.exceptions import AuthenticationError
from data_collector.infrastructure.logging import configure_logging
from data_collector.mcp.auth import (
    authorization_server_metadata,
    protected_resource_metadata,
    resolve_http_actor,
    set_mcp_actor,
)
from data_collector.mcp.tools import build_mcp_server


def create_mcp_http_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> Starlette:
    """Create Starlette ASGI app serving Streamable HTTP `/mcp` and OAuth 2.1 metadata."""
    cfg = settings or get_settings()
    ctr = container or build_container(cfg)
    mcp = build_mcp_server(ctr)
    mcp_asgi = mcp.streamable_http_app()

    async def oauth_protected_resource(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(protected_resource_metadata(cfg))

    async def oauth_auth_server(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(authorization_server_metadata(cfg))

    async def health_live(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "live"})

    async def auth_and_origin_middleware(request: Request, call_next: Any) -> Any:
        if request.url.path in {
            "/health/live",
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
        }:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin and cfg.allowed_origins and origin not in cfg.allowed_origins:
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        try:
            actor = resolve_http_actor(ctr, dict(request.headers))
        except AuthenticationError as exc:
            resp = JSONResponse(
                {"error": {"code": "UNAUTHENTICATED", "message": exc.message}},
                status_code=401,
            )
            prm_url = f"{cfg.mcp_public_url.rstrip('/mcp')}/.well-known/oauth-protected-resource"
            resp.headers["WWW-Authenticate"] = f'Bearer resource_metadata="{prm_url}"'
            return resp

        set_mcp_actor(actor)
        try:
            return await call_next(request)
        finally:
            set_mcp_actor(None)

    app = Starlette(
        routes=[
            Route("/health/live", health_live, methods=["GET"]),
            Route(
                "/.well-known/oauth-protected-resource", oauth_protected_resource, methods=["GET"]
            ),
            Route("/.well-known/oauth-authorization-server", oauth_auth_server, methods=["GET"]),
            Mount("/", app=mcp_asgi),
        ]
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=auth_and_origin_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "Mcp-Session-Id"],
    )
    return app


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg.log_level)
    app = create_mcp_http_app(cfg)
    uvicorn.run(app, host=cfg.mcp_host, port=cfg.mcp_port)
