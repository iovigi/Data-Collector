"""Host the MCP Streamable HTTP + OAuth ASGI app inside the IIS FastCGI (WSGI) process.

No socket, port or second HTTP server is involved: each IIS FastCGI process owns one
asyncio event loop thread; WSGI requests for MCP paths are handed to the ASGI app on that
loop by ``a2wsgi.ASGIMiddleware`` and the complete response is written back through IIS.

The MCP app runs in **stateless, JSON-response** Streamable HTTP mode: every ``POST /mcp``
carries one JSON-RPC message and receives one ``application/json`` body. There is no
server-held MCP session and no SSE stream, so nothing depends on a long-lived connection,
on which FastCGI process serves the next request, or on response streaming through IIS
and Cloudflare. ``GET /mcp`` (standalone SSE stream) answers 405, which the MCP Streamable
HTTP specification permits.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from a2wsgi import ASGIMiddleware

from data_collector.config import Settings
from data_collector.container import Container

MCP_PATH_PREFIXES = ("/mcp", "/.well-known/", "/oauth/")


def is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/") or path.startswith(MCP_PATH_PREFIXES[1:])


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self.loop.run_forever, name="dc-mcp-loop", daemon=True
        )
        self._thread.start()

    def run(self, coro: Any, timeout: float = 30.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


def build_mcp_wsgi(cfg: Settings, container: Container) -> Callable[..., Any]:
    from data_collector.mcp.server_http import create_mcp_http_app, public_transport_security

    asgi_app = create_mcp_http_app(
        cfg,
        container=container,
        stateless_http=True,
        json_response=True,
        transport_security=public_transport_security(cfg),
    )
    loop_thread = _LoopThread()

    # a2wsgi does not run ASGI lifespan. Run it in one long-lived task on the bridge loop so
    # the MCP SDK session manager (an anyio task group, which must be entered and exited in
    # the same task) is running before the first request and for the life of the process.
    ready: concurrent.futures.Future[None] = concurrent.futures.Future()

    async def _lifespan_runner() -> None:
        try:
            lifespan_cm: AbstractAsyncContextManager[Any] = asgi_app.router.lifespan_context(
                asgi_app
            )
            async with lifespan_cm:
                ready.set_result(None)
                await asyncio.Event().wait()  # until the process exits
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise

    runner = asyncio.run_coroutine_threadsafe(_lifespan_runner(), loop_thread.loop)
    ready.result(timeout=30)
    middleware = ASGIMiddleware(asgi_app, loop=loop_thread.loop, wait_time=30.0)
    middleware._dc_lifespan_task = runner  # type: ignore[attr-defined]  # keep a reference
    return StatelessMcpMethodGuard(middleware)


class StatelessMcpMethodGuard:
    """Answer ``GET``/``DELETE /mcp`` with 405 in stateless JSON mode.

    The MCP Streamable HTTP spec lets a server that offers no standalone SSE stream answer
    ``GET`` with 405, and a server without sessions answer ``DELETE`` with 405. The SDK's
    stateless mode would otherwise open an SSE stream that never ends, which IIS FastCGI
    (buffered responses) cannot deliver.
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        path = str(environ.get("PATH_INFO", ""))
        method = str(environ.get("REQUEST_METHOD", "")).upper()
        if path in ("/mcp", "/mcp/") and method in ("GET", "DELETE"):
            body = b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"Method not allowed: stateless server, POST only"}}'
            start_response(
                "405 Method Not Allowed",
                [
                    ("Content-Type", "application/json"),
                    ("Allow", "POST"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-store"),
                ],
            )
            return [body]
        return self.app(environ, start_response)


class PathDispatcher:
    """Route MCP/OAuth paths to the MCP WSGI bridge, everything else to Flask (in-process)."""

    def __init__(self, default_app: Callable[..., Any], mcp_app: Callable[..., Any]) -> None:
        self.default_app = default_app
        self.mcp_app = mcp_app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        path = str(environ.get("PATH_INFO", ""))
        if is_mcp_path(path):
            return self.mcp_app(environ, start_response)
        return self.default_app(environ, start_response)
