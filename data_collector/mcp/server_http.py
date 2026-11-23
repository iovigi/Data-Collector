"""Remote HTTPS Streamable HTTP MCP server (`dc-mcp-http`) with OAuth 2.1 consent & CSRF."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import html
import secrets
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode, urlparse

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


def _sign_csrf(nonce: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{nonce}.{mac}"


def _verify_csrf(cookie_val: str, form_val: str, secret: str) -> bool:
    if not cookie_val or not form_val or not hmac.compare_digest(cookie_val, form_val):
        return False
    try:
        nonce, mac = form_val.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected)


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


def public_transport_security(cfg: Settings) -> Any:
    """DNS-rebinding protection bound to the public MCP host (e.g. behind IIS/Cloudflare)."""
    from mcp.server.transport_security import TransportSecuritySettings

    host = urlparse(cfg.mcp_public_url).netloc
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host],
        allowed_origins=list(cfg.allowed_origins),
    )


def create_mcp_http_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
    stateless_http: bool = False,
    json_response: bool = False,
    transport_security: Any | None = None,
) -> Starlette:
    """Create Starlette ASGI app serving Streamable HTTP `/mcp` and OAuth 2.1 endpoints."""
    cfg = settings or get_settings()
    ctr = container or build_container(cfg)
    mcp = build_mcp_server(
        ctr,
        stateless_http=stateless_http,
        json_response=json_response,
        transport_security=transport_security,
    )
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
        ctr.redis.rate_limiter.check(
            f"oauth_reg:{request.client.host if request.client else 'unknown'}",
            20,
            is_mutation=True,
        )
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

    async def oauth_authorize_get(request: Request) -> Any:
        q = request.query_params
        cid = q.get("client_id", "")
        ruri = q.get("redirect_uri", "")
        raw_scope = q.get("scope", "workspace:read collection:read records:read")
        cchal = q.get("code_challenge", "")
        cmeth = q.get("code_challenge_method", "S256")
        res = q.get("resource", "") or None
        try:
            client_doc, scopes, _ = ctr.oauth_service.validate_authorize_request(
                client_id=cid,
                redirect_uri=ruri,
                raw_scope=raw_scope,
                code_challenge=cchal,
                code_challenge_method=cmeth,
                resource=res,
            )
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message}, status_code=400
            )

        csrf_val = _sign_csrf(secrets.token_hex(16), cfg.intent_secret_key)
        origin = urlparse(ruri).netloc
        scope_items = "".join(f"<li>{html.escape(s)}</li>" for s in scopes)
        form = (
            "<html><body><h2>Authorize MCP Client</h2>"
            f"<p>Application: <strong>{html.escape(client_doc['client_name'])}</strong> "
            f"(redirect host: <code>{html.escape(origin)}</code>)</p>"
            f"<p>Requested scopes:</p><ul>{scope_items}</ul>"
            "<form method='post' action='/oauth/authorize'>"
            f"<input type='hidden' name='csrf_token' value='{csrf_val}'/>"
            f"<input type='hidden' name='client_id' value='{html.escape(cid)}'/>"
            f"<input type='hidden' name='redirect_uri' value='{html.escape(ruri)}'/>"
            f"<input type='hidden' name='state' value='{html.escape(q.get('state', ''))}'/>"
            f"<input type='hidden' name='scope' value='{html.escape(' '.join(scopes))}'/>"
            f"<input type='hidden' name='code_challenge' value='{html.escape(cchal)}'/>"
            f"<input type='hidden' name='code_challenge_method' value='{html.escape(cmeth)}'/>"
            f"<input type='hidden' name='resource' value='{html.escape(res or '')}'/>"
            "Email: <input name='email' type='email' required/><br/>"
            "Password: <input name='password' type='password' required/><br/>"
            "<button type='submit' name='consent' value='approve'>Approve</button> "
            "<button type='submit' name='consent' value='deny'>Deny</button>"
            "</form></body></html>"
        )
        resp = HTMLResponse(form)
        resp.set_cookie(
            "dc_oauth_csrf",
            csrf_val,
            httponly=True,
            samesite="lax",
            secure=(cfg.app_env == "production"),
            max_age=300,
        )
        return resp

    async def oauth_authorize_post(request: Request) -> Any:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
        else:
            form_data = await request.form()
            data = dict(form_data)

        cookie_csrf = request.cookies.get("dc_oauth_csrf", "")
        form_csrf = str(data.get("csrf_token", ""))
        if not _verify_csrf(cookie_csrf, form_csrf, cfg.intent_secret_key):
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Invalid or missing CSRF token"},
                status_code=403,
            )

        redirect_uri = str(data.get("redirect_uri", ""))
        state = str(data.get("state", ""))
        client_id = str(data.get("client_id", ""))
        raw_scope = str(data.get("scope", "workspace:read collection:read records:read"))
        code_challenge = str(data.get("code_challenge", ""))
        code_challenge_method = str(data.get("code_challenge_method", ""))
        resource = str(data.get("resource", "")) or None

        try:
            _, scopes, _ = ctr.oauth_service.validate_authorize_request(
                client_id=client_id,
                redirect_uri=redirect_uri,
                raw_scope=raw_scope,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                resource=resource,
            )
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message}, status_code=400
            )

        if str(data.get("consent", "approve")).lower() == "deny":
            params: dict[str, str] = {"error": "access_denied"}
            if state:
                params["state"] = state
            sep = "&" if "?" in redirect_uri else "?"
            return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)

        try:
            email = str(data.get("email", ""))
            password = str(data.get("password", ""))
            ctr.auth_service.login(
                email,
                password,
                client_ip=request.client.host if request.client else "unknown",
            )
            user = ctr.users.find_by_email(email)
            assert user is not None
            code = ctr.oauth_service.create_authorization_code(
                client_id=client_id,
                redirect_uri=redirect_uri,
                user_id=str(user["_id"]),
                email=str(user["email"]),
                scopes=scopes,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                resource=resource,
            )
            ok_params: dict[str, str] = {"code": code}
            if state:
                ok_params["state"] = state
            sep = "&" if "?" in redirect_uri else "?"
            target_url = f"{redirect_uri}{sep}{urlencode(ok_params)}"
            return RedirectResponse(url=target_url, status_code=302)
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message},
                status_code=exc.http_status,
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
            if grant_type == "authorization_code":
                tok = ctr.oauth_service.exchange_code(
                    code=str(data.get("code", "")),
                    client_id=str(data.get("client_id", "")),
                    redirect_uri=str(data.get("redirect_uri", "")),
                    code_verifier=str(data.get("code_verifier", "")),
                )
                return JSONResponse(tok)
            if grant_type == "refresh_token":
                tok = ctr.oauth_service.exchange_refresh_token(
                    refresh_token=str(data.get("refresh_token", "")),
                    client_id=str(data.get("client_id", "")),
                    raw_scope=str(data.get("scope", "")) or None,
                )
                return JSONResponse(tok)
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": exc.message},
                status_code=400,
            )

    async def oauth_revoke(request: Request) -> JSONResponse:
        form_data = await request.form()
        tok = str(form_data.get("token", ""))
        cid = str(form_data.get("client_id", ""))
        try:
            if tok:
                ctr.oauth_service.revoke_token(tok, client_id=cid)
            return JSONResponse({"status": "revoked"})
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message},
                status_code=400,
            )

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

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=routes, lifespan=lifespan)
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
