"""Remote HTTPS Streamable HTTP MCP server (`dc-mcp-http`) with OAuth 2.1 consent & CSRF."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
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
from data_collector.infrastructure.crypto import sign_intent_token, verify_intent_token
from data_collector.infrastructure.logging import configure_logging
from data_collector.infrastructure.oauth import WRITE_OAUTH_SCOPES
from data_collector.mcp.auth import (
    authorization_server_metadata,
    protected_resource_metadata,
    reset_mcp_actor,
    resolve_http_actor,
    set_mcp_actor,
    www_authenticate_challenge,
)
from data_collector.mcp.consent import (
    SECURITY_HEADERS,
    render_consent,
    render_message,
    render_signin,
)
from data_collector.mcp.tools import build_mcp_server

_PUBLIC_PATHS = frozenset(
    {
        "/health/live",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
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
            resp = JSONResponse(
                {"error": {"code": "UNAUTHENTICATED", "message": exc.message}},
                status_code=401,
                headers={"WWW-Authenticate": www_authenticate_challenge(self.cfg)},
            )
            await resp(scope, receive, send)
            return

        scope["dc_actor"] = actor
        token = set_mcp_actor(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_mcp_actor(token)


async def _read_body(request: Request) -> dict[str, Any] | None:
    """JSON or form body as a dict; None when malformed (callers answer 400, never 500)."""
    try:
        if "application/json" in request.headers.get("content-type", ""):
            data = await request.json()
            return data if isinstance(data, dict) else None
        return dict(await request.form())
    except Exception:  # malformed JSON / multipart
        return None


def _bad_body() -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_request", "error_description": "Malformed request body"},
        status_code=400,
    )


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
        try:
            ctr.redis.rate_limiter.check(
                f"oauth_reg:{request.client.host if request.client else 'unknown'}",
                20,
                is_mutation=True,
            )
        except DomainError as exc:  # rate limited / limiter unavailable -> 429 / 503, not 500
            headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message},
                status_code=exc.http_status,
                headers=headers,
            )
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "Body must be JSON"},
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "Body must be an object"},
                status_code=400,
            )
        try:
            res = ctr.oauth_service.register_client(
                client_name=str(body.get("client_name", "mcp-client")),
                redirect_uris=list(body.get("redirect_uris", [])),
                scope=str(body["scope"]) if body.get("scope") else None,
            )
            return JSONResponse(res, status_code=201)
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message}, status_code=400
            )

    _CONSENT_TTL = 600
    _AUTH_FIELDS = (
        "client_id",
        "redirect_uri",
        "state",
        "scope",
        "code_challenge",
        "code_challenge_method",
        "resource",
    )

    def _html(body: str, status: int = 200, csrf: str | None = None) -> HTMLResponse:
        resp = HTMLResponse(body, status_code=status, headers=dict(SECURITY_HEADERS))
        if csrf is not None:
            resp.set_cookie(
                "dc_oauth_csrf",
                csrf,
                httponly=True,
                samesite="lax",
                secure=(cfg.app_env == "production"),
                max_age=_CONSENT_TTL,
            )
        return resp

    def _redirect(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)

    def _deny_redirect(redirect_uri: str, state: str) -> RedirectResponse:
        params: dict[str, str] = {"error": "access_denied"}
        if state:
            params["state"] = state
        return _redirect(redirect_uri, params)

    def _signin_page(
        fields: dict[str, str], client_doc: dict[str, Any], scopes: list[str], error: str | None
    ) -> HTMLResponse:
        csrf_val = _sign_csrf(secrets.token_hex(16), cfg.intent_secret_key)
        page = render_signin(
            client_name=str(client_doc.get("client_name", "MCP client")),
            redirect_host=urlparse(fields["redirect_uri"]).netloc,
            scopes=scopes,
            writes_enabled=cfg.mcp_allow_writes,
            hidden={**fields, "scope": " ".join(scopes)},
            csrf_token=csrf_val,
            error=error,
        )
        return _html(page, 401 if error else 200, csrf=csrf_val)

    def _validate(fields: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
        client_doc, scopes, _ = ctr.oauth_service.validate_authorize_request(
            client_id=fields["client_id"],
            redirect_uri=fields["redirect_uri"],
            raw_scope=fields["scope"],
            code_challenge=fields["code_challenge"],
            code_challenge_method=fields["code_challenge_method"],
            resource=fields["resource"] or None,
        )
        return client_doc, scopes

    def _fields(src: Any) -> dict[str, str]:
        out = {k: str(src.get(k, "") or "") for k in _AUTH_FIELDS}
        out["code_challenge_method"] = out["code_challenge_method"] or "S256"
        return out

    async def oauth_authorize_get(request: Request) -> Any:
        fields = _fields(request.query_params)
        try:
            client_doc, scopes = _validate(fields)
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message}, status_code=400
            )
        return _signin_page(fields, client_doc, scopes, None)

    def _user_workspaces(user_id: str) -> list[dict[str, Any]]:
        out = []
        for ws in ctr.workspaces.list_for_principal(user_id, limit=100):
            if ws.get("status", "active") != "active":
                continue
            role = ctr.workspaces.get_membership_role(ws["id"], user_id) or "viewer"
            out.append({"id": ws["id"], "name": ws["name"], "slug": ws["slug"], "role": role})
        return out

    async def _step_login(request: Request, data: dict[str, Any]) -> Any:
        fields = _fields(data)
        try:
            client_doc, scopes = _validate(fields)
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message}, status_code=400
            )
        if str(data.get("consent", "")).lower() == "deny":
            return _deny_redirect(fields["redirect_uri"], fields["state"])
        email = str(data.get("email", ""))
        try:
            ctr.auth_service.login(
                email,
                str(data.get("password", "")),
                client_ip=request.client.host if request.client else "unknown",
            )
        except DomainError as exc:
            return _signin_page(fields, client_doc, scopes, exc.message)
        user = ctr.users.find_by_email(email)
        if user is None:  # pragma: no cover - login just succeeded
            return _signin_page(fields, client_doc, scopes, "Invalid credentials")
        user_id = str(user["_id"])
        workspaces = _user_workspaces(user_id)
        if not workspaces:
            return _html(
                render_message(
                    "No workspace",
                    "Your account is not a member of any active workspace yet. Create or "
                    "join one in the Data Collector admin, then connect again.",
                ),
                403,
            )
        ticket = sign_intent_token(
            {
                "op": "oauth_consent",
                "uid": user_id,
                "email": str(user["email"]),
                "f": fields,
                "scopes": scopes,
            },
            cfg.intent_secret_key,
            ttl_seconds=_CONSENT_TTL,
        )
        csrf_val = _sign_csrf(secrets.token_hex(16), cfg.intent_secret_key)
        page = render_consent(
            client_name=str(client_doc.get("client_name", "MCP client")),
            redirect_host=urlparse(fields["redirect_uri"]).netloc,
            email=str(user["email"]),
            scopes=scopes,
            writes_enabled=cfg.mcp_allow_writes,
            workspaces=workspaces,
            ticket=ticket,
            csrf_token=csrf_val,
        )
        return _html(page, csrf=csrf_val)

    async def _step_consent(data: dict[str, Any]) -> Any:
        ticket = verify_intent_token(str(data.get("ticket", "")), cfg.intent_secret_key)
        if ticket is None or ticket.get("op") != "oauth_consent":
            return _html(
                render_message("Session expired", "Please start the connection again."), 400
            )
        fields = {k: str(v) for k, v in dict(ticket.get("f") or {}).items()}
        if str(data.get("consent", "")).lower() != "approve":
            return _deny_redirect(fields.get("redirect_uri", ""), fields.get("state", ""))
        try:
            client_doc, scopes = _validate(fields)
        except DomainError as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": exc.message}, status_code=400
            )
        user_id = str(ticket["uid"])
        workspace_id = str(data.get("workspace_id", ""))
        if workspace_id not in {w["id"] for w in _user_workspaces(user_id)}:
            return _html(render_message("Not allowed", "Choose one of your workspaces."), 403)
        if str(data.get("allow_writes", "")) != "on" or not cfg.mcp_allow_writes:
            scopes = [sc for sc in scopes if sc not in WRITE_OAUTH_SCOPES]
        if not scopes:
            scopes = ["workspace:read", "collection:read", "records:read"]
        try:
            code = ctr.oauth_service.create_authorization_code(
                client_id=fields["client_id"],
                redirect_uri=fields["redirect_uri"],
                user_id=user_id,
                email=str(ticket.get("email", "")),
                scopes=scopes,
                code_challenge=fields["code_challenge"],
                code_challenge_method=fields["code_challenge_method"],
                resource=fields["resource"] or None,
                workspace_id=workspace_id,
            )
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message}, status_code=exc.http_status
            )
        ctr.audit_service.record(
            tenant=workspace_id,
            actor_id=user_id,
            action="oauth.grant",
            target=f"oauth_client:{fields['client_id']}",
            decision="allow",
            metadata={
                "client_name": client_doc.get("client_name"),
                "scopes": scopes,
                "redirect_host": urlparse(fields["redirect_uri"]).netloc,
            },
        )
        params = {"code": code}
        if fields.get("state"):
            params["state"] = fields["state"]
        return _redirect(fields["redirect_uri"], params)

    async def oauth_authorize_post(request: Request) -> Any:
        data = await _read_body(request)
        if data is None:
            return _bad_body()

        cookie_csrf = request.cookies.get("dc_oauth_csrf", "")
        form_csrf = str(data.get("csrf_token", ""))
        if not _verify_csrf(cookie_csrf, form_csrf, cfg.intent_secret_key):
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Invalid or missing CSRF token"},
                status_code=403,
            )

        step = str(data.get("step", ""))
        if step == "login":
            return await _step_login(request, data)
        if step == "consent":
            return await _step_consent(data)

        # Legacy one-shot form (email + password + consent): kept for existing automation
        # and the deployment verifier. Grants from it are not bound to a workspace.
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
            return _deny_redirect(redirect_uri, state)

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
            return _redirect(redirect_uri, ok_params)
        except DomainError as exc:
            return JSONResponse(
                {"error": exc.code, "error_description": exc.message},
                status_code=exc.http_status,
            )

    async def oauth_token(request: Request) -> JSONResponse:
        data = await _read_body(request)
        if data is None:
            return _bad_body()
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
        # RFC 9728 path-suffixed form for a resource at /mcp (tried first by MCP clients).
        Route(
            "/.well-known/oauth-protected-resource/mcp",
            oauth_protected_resource,
            methods=["GET"],
        ),
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
