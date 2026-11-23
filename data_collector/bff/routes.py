"""Python BFF endpoints replacing the former Next.js server routes.

* ``POST /api/auth/login|logout|refresh`` - browser session lifecycle (in-process AuthService).
* ``/api/backend/<path>`` - allowlisted REST v1 calls for the logged-in browser session.

``/api/backend`` is not a network proxy: the request is dispatched *inside this process*
to the same Flask app's WSGI callable for ``/api/v1/<path>``, with the session's access
token attached. All API authentication, RBAC, rate limiting, validation and error handling
therefore run exactly as for any other API client.
"""

from __future__ import annotations

import logging

from flask import Blueprint, Flask, Response, current_app, jsonify, request
from flask.typing import ResponseReturnValue
from werkzeug.test import EnvironBuilder, run_wsgi_app

from data_collector.api.errors import error_response
from data_collector.api.middleware import get_container
from data_collector.bff.allowlist import is_allowed_backend_path
from data_collector.bff.csrf import create_csrf_token, is_trusted_origin, verify_csrf_token
from data_collector.bff.session_store import WebSessionStore
from data_collector.domain.exceptions import BadRequestError
from data_collector.infrastructure.logging import get_request_id, set_request_context

logger = logging.getLogger(__name__)

bff_bp = Blueprint("web_bff", __name__)

_FORWARD_REQUEST_HEADERS = ("Content-Type", "Idempotency-Key", "If-Match", "Accept")
_FORWARD_RESPONSE_HEADERS = (
    "Content-Type",
    "Content-Disposition",
    "Content-Length",
    "X-Request-Id",
    "X-Content-SHA256",
    "Retry-After",
    "ETag",
    "Deprecation",
    "Sunset",
)
_SAFE_METHODS = frozenset({"GET", "HEAD"})


# --------------------------------------------------------------------------- helpers


def _secure_cookies() -> bool:
    return get_container().settings.app_env == "production"


def cookie_names() -> tuple[str, str]:
    """``__Host-`` cookies (Secure, host-only, path=/) in production."""
    if _secure_cookies():
        return "__Host-dc_sid", "__Host-dc_csrf"
    return "dc_sid", "dc_csrf"


def _store() -> WebSessionStore:
    store = current_app.extensions.get("dc_web_sessions")
    if store is None:
        container = get_container()
        store = WebSessionStore(container.redis.client, container.settings.web_session_ttl_seconds)
        current_app.extensions["dc_web_sessions"] = store
    return store  # type: ignore[no-any-return]


def _secret() -> str:
    return get_container().settings.web_session_secret


def _set_session_cookies(resp: Response, sid: str) -> None:
    sid_name, csrf_name = cookie_names()
    ttl = get_container().settings.web_session_ttl_seconds
    secure = _secure_cookies()
    resp.set_cookie(sid_name, sid, max_age=ttl, path="/", secure=secure, httponly=True, samesite="Lax")
    resp.set_cookie(
        csrf_name,
        create_csrf_token(_secret(), sid),
        max_age=ttl,
        path="/",
        secure=secure,
        httponly=False,  # double-submit: same-origin JS reads it into X-CSRF-Token
        samesite="Lax",
    )


def _clear_session_cookies(resp: Response) -> None:
    secure = _secure_cookies()
    for name in cookie_names():
        resp.delete_cookie(name, path="/", secure=secure, samesite="Lax")


def _origin_ok() -> bool:
    return is_trusted_origin(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        get_container().settings.allowed_origins,
    )


def _csrf_ok(sid: str) -> bool:
    _, csrf_name = cookie_names()
    return verify_csrf_token(
        _secret(), sid, request.cookies.get(csrf_name), request.headers.get("X-CSRF-Token")
    )


def _forbidden(message: str) -> Response:
    return error_response(code="FORBIDDEN", message=message, status=403)


def _unauthenticated(message: str, *, clear: bool = False) -> Response:
    resp = error_response(code="UNAUTHENTICATED", message=message, status=401)
    if clear:
        _clear_session_cookies(resp)
    return resp


def _audit(action: str, actor_id: str, decision: str = "allow") -> None:
    try:
        get_container().audit_service.record(
            tenant=None, actor_id=actor_id, action=action, target="web_session", decision=decision
        )
    except Exception:  # pragma: no cover - audit must never break auth flows
        logger.exception("Audit record failed")


# --------------------------------------------------------------------------- auth


@bff_bp.post("/api/auth/login")
def bff_login() -> ResponseReturnValue:
    if not _origin_ok():
        return _forbidden("Untrusted request origin")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    email = str(body.get("email") or "")
    password = str(body.get("password") or "")

    container = get_container()
    tokens = container.auth_service.login(
        email, password, client_ip=request.remote_addr or "unknown"
    )
    actor = container.auth_service.authenticate_bearer(tokens["access_token"])

    store = _store()
    sid_name, _ = cookie_names()
    previous = request.cookies.get(sid_name)
    if previous:  # session fixation: never keep a pre-login session id
        store.delete(previous)
    sid = store.create(tokens, user_id=actor.principal_id, email=actor.email)

    resp = jsonify(
        {"authenticated": True, "user": {"principal_id": actor.principal_id, "email": actor.email}}
    )
    _set_session_cookies(resp, sid)
    return resp


@bff_bp.post("/api/auth/logout")
def bff_logout() -> ResponseReturnValue:
    sid_name, _ = cookie_names()
    sid = request.cookies.get(sid_name, "")
    if sid:
        if not _origin_ok() or not _csrf_ok(sid):
            return _forbidden("Invalid CSRF token or origin")
        store = _store()
        session = store.get(sid)
        if session is not None:
            refresh_token = str(session.get("refresh_token", ""))
            if refresh_token:
                get_container().auth_service.logout(refresh_token)  # revokes token family
            _audit("auth.web_logout", str(session.get("user_id", "unknown")))
        store.delete(sid)
    resp = jsonify({"status": "logged_out"})
    _clear_session_cookies(resp)
    return resp


@bff_bp.post("/api/auth/refresh")
def bff_refresh() -> ResponseReturnValue:
    sid_name, _ = cookie_names()
    sid = request.cookies.get(sid_name, "")
    if not sid:
        return _unauthenticated("No active session")
    if not _origin_ok() or not _csrf_ok(sid):
        return _forbidden("Invalid CSRF token or origin")
    updated = _store().refresh(sid, get_container().auth_service, force=True)
    if updated is None:
        return _unauthenticated("Session expired", clear=True)
    return jsonify({"authenticated": True, "expires_at": int(updated["expires_at"]) * 1000})


# --------------------------------------------------------------------------- backend


def _raw_path_suspicious() -> bool:
    for key in ("REQUEST_URI", "RAW_URI", "HTTP_X_ORIGINAL_URL", "UNENCODED_URL"):
        raw = str(request.environ.get(key, "")).split("?", 1)[0].lower()
        if any(tok in raw for tok in ("%2e", "%2f", "%5c", "%25", "\\")):
            return True
    return False


def _dispatch_v1(app: Flask, subpath: str, access_token: str, body: bytes | None) -> Response:
    headers: dict[str, str] = {"Authorization": f"Bearer {access_token}"}
    for name in _FORWARD_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value:
            headers[name] = value
    builder = EnvironBuilder(
        path=f"/api/v1/{subpath}",
        method=request.method,
        query_string=request.query_string.decode("latin-1"),
        headers=headers,
        data=body,
        environ_overrides={
            "REMOTE_ADDR": request.remote_addr or "unknown",
            "wsgi.url_scheme": request.scheme,
            "HTTP_HOST": request.host,
            "dc.internal_dispatch": True,
        },
    )
    environ = builder.get_environ()
    outer_request_id = get_request_id()
    try:
        inner = app.extensions.get("dc_inner_wsgi", app.wsgi_app)
        app_iter, status, resp_headers = run_wsgi_app(inner, environ, buffered=False)
    finally:
        set_request_context(outer_request_id, outer_request_id)
    out = Response(app_iter, status=status, direct_passthrough=True)
    out.headers.clear()
    for name in _FORWARD_RESPONSE_HEADERS:
        value = resp_headers.get(name)
        if value:
            out.headers[name] = value
    out.headers["Cache-Control"] = "no-store"
    return out


@bff_bp.route(
    "/api/backend/<path:subpath>", methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"]
)
def bff_backend(subpath: str) -> ResponseReturnValue:
    if _raw_path_suspicious() or not is_allowed_backend_path(subpath):
        return _forbidden("Backend path is not allowlisted")

    sid_name, _ = cookie_names()
    sid = request.cookies.get(sid_name, "")
    if not sid:
        return _unauthenticated("Authentication required")

    method = request.method.upper()
    if method not in _SAFE_METHODS and (not _origin_ok() or not _csrf_ok(sid)):
        return _forbidden("Invalid or missing CSRF token or origin")

    store = _store()
    session = store.get(sid)
    if session is None:
        return _unauthenticated("Session expired", clear=True)

    container = get_container()
    if store.needs_refresh(session):
        refreshed = store.refresh(sid, container.auth_service)
        if refreshed is None:
            return _unauthenticated("Session expired", clear=True)
        session = refreshed

    body = None if method in _SAFE_METHODS else request.get_data(cache=False)
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    resp = _dispatch_v1(app, subpath, str(session["access_token"]), body)

    retryable = method == "GET" or bool(request.headers.get("Idempotency-Key"))
    if resp.status_code == 401 and retryable:
        resp.close()
        refreshed = store.refresh(sid, container.auth_service, force=True)
        if refreshed is None:
            return _unauthenticated("Session expired", clear=True)
        resp = _dispatch_v1(app, subpath, str(refreshed["access_token"]), body)
    return resp


def register_bff(app: Flask) -> None:
    settings = app.extensions["container"].settings
    if settings.app_env == "production" and len(settings.web_session_secret.strip()) < 32:
        raise RuntimeError("WEB_SESSION_SECRET (>= 32 chars) is required to serve the browser BFF")
    app.register_blueprint(bff_bp)
