"""Remote HTTPS Streamable HTTP MCP server (`dc-mcp-http`) with OAuth 2.1 & pure ASGI isolation."""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlencode

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from data_collector.config import Settings, get_settings
from data_collector.container import Container, build_container
from data_collector.domain.exceptions import AuthenticationError, DomainError
from data_collector.infrastructure.logging import configure_logging
from data_collector.mcp.auth import (
    authorization_server_metadata,
    protected_resource_metadata,
    reset_mcp_actor,
    resolve_http_actor,
    set_mcp_actor,
)
from data_collector.mcp.tools import build_mcp_server

_PUBLIC_PATHS = frozenset(
    {
        "/health/live",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/.well-known/jwks.json",
        "/oauth/authorize",
        "/oauth/token",
        "/oauth/revoke",
        "/oauth/register",
    }
)


class MCPAuthASGIMiddleware:
    """Pure ASGI middleware that isolates verified Actor per request without BaseHTTPMiddleware."""

    def __init__(self, app: ASGIApp, container: Container, cfg: Settings) -> None:
        self.app = app
        self.container = container
        self.cfg = cfg

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        origin = headers.get("origin")
        if origin and self.cfg.allowed_origins and origin not in self.cfg.allowed_origins:
            resp = JSONResponse({"error": "Origin not allowed"}, status_code=403)
            await resp(scope, receive, send)
            return

        try:
            actor = resolve_http_actor(self.container, headers)
        except AuthenticationError as exc:
            prm_url = (
                f"{self.cfg.mcp_public_url.removesuffix('/mcp').rstrip('/')}"
                "/.well-known/oauth-protected-resource"
            )
            resp = JSONResponse(
                {"error": {"code": "UNAUTHENTICATED", "message": exc.message}},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{prm_url}"'},
            )
            await resp(scope, receive, send)
            return

        scope["dc_actor"] = actor
        token = set_mcp_actor(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_mcp_actor(token)


def create_mcp_http_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> Starlette:
    """Create Starlette ASGI app serving Streamable HTTP `/mcp` and OAuth 2.1 endpoints."""
    cfg = settings or get_settings()
    ctr = container or build_container(cfg)
    mcp = build_mcp_server(ctr)
    mcp_asgi = mcp.streamable_http_app()

    async def oauth_protected_resource(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(protected_resource_metadata(cfg))

    async def oauth_auth_server(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(authorization_server_metadata(cfg))

    async def oauth_jwks(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(ctr.oauth_service.jwks())

    async def health_live(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"status": "live"})

    async def oauth_register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            res = ctr.oauth_service.register_client(
                client_name=str(body.get("client_name", "mcp-client")),
                redirect_uris=list(body.get("redirect_uris", [])),
                scope=str(body.get("scope", "workspace:read collection:read records:read")),
            )
            return JSONResponse(res, status_code=201)
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message}, status_code=400
            )

    async def oauth_authorize_get(request: Request) -> HTMLResponse:
        q = request.query_params
        cid = html.escape(q.get("client_id", ""))
        ruri = html.escape(q.get("redirect_uri", ""))
        state = html.escape(q.get("state", ""))
        scope = html.escape(q.get("scope", "workspace:read collection:read records:read"))
        cchal = html.escape(q.get("code_challenge", ""))
        cmeth = html.escape(q.get("code_challenge_method", "S256"))
        res = html.escape(q.get("resource", ""))
        form = (
            "<html><body><h2>Data Collector OAuth 2.1</h2>"
            "<form method='post' action='/oauth/authorize'>"
            f"<input type='hidden' name='client_id' value='{cid}'/>"
            f"<input type='hidden' name='redirect_uri' value='{ruri}'/>"
            f"<input type='hidden' name='state' value='{state}'/>"
            f"<input type='hidden' name='scope' value='{scope}'/>"
            f"<input type='hidden' name='code_challenge' value='{cchal}'/>"
            f"<input type='hidden' name='code_challenge_method' value='{cmeth}'/>"
            f"<input type='hidden' name='resource' value='{res}'/>"
            "Email: <input name='email' type='email' required/><br/>"
            "Password: <input name='password' type='password' required/><br/>"
            "<button type='submit'>Authorize</button></form></body></html>"
        )
        return HTMLResponse(form)

    async def oauth_authorize_post(request: Request) -> Any:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
        else:
            form_data = await request.form()
            data = dict(form_data)
        try:
            email = str(data.get("email", ""))
            password = str(data.get("password", ""))
            ctr.auth_service.login(
                email, password, client_ip=request.client.host if request.client else "unknown"
            )
            user = ctr.users.find_by_email(email)
            assert user is not None
            scopes = [
                s
                for s in str(
                    data.get("scope", "workspace:read collection:read records:read")
                ).split()
                if s
            ]
            redirect_uri = str(data.get("redirect_uri", ""))
            code = ctr.oauth_service.create_authorization_code(
                client_id=str(data.get("client_id", "")),
                redirect_uri=redirect_uri,
                user_id=str(user["_id"]),
                email=str(user["email"]),
                scopes=scopes,
                code_challenge=str(data.get("code_challenge", "")),
                code_challenge_method=str(data.get("code_challenge_method", "")),
                resource=str(data.get("resource", "")) or None,
            )
            params: dict[str, str] = {"code": code}
            if data.get("state"):
                params["state"] = str(data["state"])
            sep = "&" if "?" in redirect_uri else "?"
            return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message}, status_code=exc.http_status
            )

    async def oauth_token(request: Request) -> JSONResponse:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
        else:
            form_data = await request.form()
            data = dict(form_data)
        try:
            grant_type = str(data.get("grant_type", ""))
            if grant_type != "authorization_code":
                return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
            tok = ctr.oauth_service.exchange_code(
                code=str(data.get("code", "")),
                client_id=str(data.get("client_id", "")),
                redirect_uri=str(data.get("redirect_uri", "")),
                code_verifier=str(data.get("code_verifier", "")),
            )
            return JSONResponse(tok)
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": exc.message}, status_code=400
            )

    async def oauth_revoke(request: Request) -> JSONResponse:
        form_data = await request.form()
        tok = str(form_data.get("token", ""))
        if tok:
            ctr.oauth_service.revoke_token(tok)
        return JSONResponse({"status": "revoked"})

    routes: list[Any] = [
        Route("/health/live", health_live, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", oauth_protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", oauth_auth_server, methods=["GET"]),
    ]
    if cfg.oauth_mode == "builtin":
        routes.extend(
            [
                Route("/.well-known/jwks.json", oauth_jwks, methods=["GET"]),
                Route("/oauth/register", oauth_register, methods=["POST"]),
                Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
                Route("/oauth/authorize", oauth_authorize_post, methods=["POST"]),
                Route("/oauth/token", oauth_token, methods=["POST"]),
                Route("/oauth/revoke", oauth_revoke, methods=["POST"]),
            ]
        )
    routes.append(Mount("/", app=mcp_asgi))

    app = Starlette(routes=routes)
    app.add_middleware(MCPAuthASGIMiddleware, container=ctr, cfg=cfg)
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
