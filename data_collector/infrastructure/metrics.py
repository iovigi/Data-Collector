"""Prometheus metrics registry for API, worker, and MCP."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "dc_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "dc_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)
MCP_TOOL_CALLS = Counter(
    "dc_mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool", "decision"],
)
JOB_EVENTS = Counter(
    "dc_jobs_total",
    "Background job state transitions",
    ["type", "state"],
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
