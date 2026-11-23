"""Serve the built Admin UI (Vite SPA) from Flask.

* ``/assets/<file>`` - content-hashed JS/CSS/fonts from ``<dist>/assets`` with a long
  immutable cache lifetime.
* Known UI routes (``/``, ``/login``, ``/onboarding/*``, ``/w/*``, ``/developer/*``) return
  ``index.html`` with ``Cache-Control: no-store`` and a strict Content-Security-Policy.
* Nothing else falls back to ``index.html``: unknown paths, ``/api/*``, ``/mcp``,
  ``/oauth/*``, ``/.well-known/*`` and health endpoints keep their own 404/JSON behaviour.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, abort, g, send_from_directory

from data_collector.api.errors import error_response

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
ASSET_MAX_AGE = 31_536_000

_UI_PREFIXES = ("/onboarding/", "/w/", "/developer/")
_UI_EXACT = frozenset({"/", "/login"})


def is_ui_route(path: str) -> bool:
    return path in _UI_EXACT or path.startswith(_UI_PREFIXES)


def register_spa(app: Flask, dist_dir: str) -> None:
    dist = Path(dist_dir).resolve() if dist_dir else None
    assets_dir = (dist / "assets") if dist else None

    def _index() -> Response:
        if dist is None or not (dist / "index.html").is_file():
            return error_response(
                code="SERVICE_UNAVAILABLE", message="Admin UI is not installed", status=503
            )
        resp = send_from_directory(dist, "index.html", mimetype="text/html", max_age=0)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp

    @app.get("/assets/<path:filename>")
    def spa_asset(filename: str) -> Response:
        if assets_dir is None or filename.endswith(".map"):
            abort(404)
        resp = send_from_directory(assets_dir, filename, max_age=ASSET_MAX_AGE)
        g.dc_cache_control = f"public, max-age={ASSET_MAX_AGE}, immutable"
        return resp

    @app.get("/favicon.svg")
    def spa_favicon() -> Response:
        if dist is None:
            abort(404)
        resp = send_from_directory(dist, "favicon.svg", max_age=86400)
        g.dc_cache_control = "public, max-age=86400"
        return resp

    @app.get("/")
    @app.get("/login")
    def spa_root() -> Response:
        return _index()

    @app.get("/onboarding/<path:_rest>")
    @app.get("/w/<path:_rest>")
    @app.get("/developer/<path:_rest>")
    def spa_deep(_rest: str) -> Response:
        return _index()
