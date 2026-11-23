"""MCP structured error mapping, output size capping, and response envelopes."""

from __future__ import annotations

import json
from typing import Any

from data_collector.domain.exceptions import DomainError


def map_domain_error(exc: Exception) -> dict[str, Any]:
    """Map DomainError or unexpected error to structured MCP error object."""
    if isinstance(exc, DomainError):
        return {
            "ok": False,
            "error": {
                "code": exc.mcp_code,
                "message": exc.message,
                "details": exc.details,
            },
        }
    return {
        "ok": False,
        "error": {
            "code": "TEMPORARY_UNAVAILABLE",
            "message": "Operation failed",
            "details": [],
        },
    }


def cap_tool_response(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Enforce maximum serialized response size; truncate `items` list if needed."""
    raw = json.dumps(payload, default=str).encode("utf-8")
    if len(raw) <= max_bytes:
        return payload

    if "items" in payload and isinstance(payload["items"], list):
        items = list(payload["items"])
        while (
            items
            and len(
                json.dumps({**payload, "items": items, "truncated": True}, default=str).encode(
                    "utf-8"
                )
            )
            > max_bytes
        ):
            items.pop()
        return {**payload, "items": items, "truncated": True}

    return {
        "ok": False,
        "error": {
            "code": "INVALID_ARGUMENT",
            "message": f"Response exceeds max {max_bytes} bytes; refine fields or limit",
            "details": [],
        },
    }
