"""Local stdio MCP server entrypoint (`dc-mcp-stdio`) for Claude Desktop / Claude Code."""

from __future__ import annotations

import asyncio
import sys

from data_collector.config import get_settings
from data_collector.container import build_container
from data_collector.infrastructure.logging import configure_logging
from data_collector.mcp.auth import resolve_stdio_actor, set_mcp_actor
from data_collector.mcp.tools import build_mcp_server


def main() -> None:
    cfg = get_settings()
    # Never write logs to stdout; stdout is reserved exclusively for MCP JSON-RPC frames.
    configure_logging(cfg.log_level, stream=sys.stderr)
    container = build_container(cfg)
    try:
        actor = resolve_stdio_actor(container)
        set_mcp_actor(actor)
        mcp = build_mcp_server(container)
        asyncio.run(mcp.run_stdio_async())
    finally:
        container.close()
