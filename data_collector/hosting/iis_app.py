"""Build the single WSGI application IIS runs through FastCGI.

One process-local composition, no sockets between parts::

    CloudflareClientIPMiddleware
      -> PathDispatcher
           /mcp, /oauth/*, /.well-known/*  -> MCP ASGI app (stateless JSON) via in-process bridge
           everything else                 -> Flask: REST /api/v1, BFF /api/auth + /api/backend,
                                              health, OpenAPI, Admin UI (SPA)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from data_collector.app import create_app
from data_collector.bff import register_iis_ui_and_bff
from data_collector.config import get_settings
from data_collector.hosting.client_ip import CloudflareClientIPMiddleware
from data_collector.hosting.env import load_deployment_env
from data_collector.hosting.logs import configure_file_logging


def build_application() -> Callable[..., Any]:
    load_deployment_env()
    cfg = get_settings()

    flask_app = create_app(cfg)
    if cfg.log_dir:
        configure_file_logging(cfg.log_level, cfg.log_dir, prefix="app")
    register_iis_ui_and_bff(flask_app, cfg.web_dist_dir)

    wsgi: Callable[..., Any] = flask_app.wsgi_app
    flask_app.extensions["dc_inner_wsgi"] = flask_app.wsgi_app  # used by the BFF dispatch
    if cfg.mcp_http_in_process:
        from data_collector.hosting.mcp_bridge import PathDispatcher, build_mcp_wsgi

        container = flask_app.extensions["container"]
        wsgi = PathDispatcher(flask_app.wsgi_app, build_mcp_wsgi(cfg, container))
    if cfg.trust_cloudflare_client_ip:
        wsgi = CloudflareClientIPMiddleware(wsgi)
    flask_app.wsgi_app = wsgi  # type: ignore[method-assign]
    return flask_app
