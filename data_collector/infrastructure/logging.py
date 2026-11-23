"""Structured JSON logging with request_id, trace_id, and secret/PII scrubbing."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "authorization",
        "x-system-auth",
        "x-api-key",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "jwt_secret_key",
        "api_key",
        "key_hash",
    }
)


def set_request_context(request_id: str | None, trace_id: str | None = None) -> None:
    _request_id_var.set(request_id)
    _trace_id_var.set(trace_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


def scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys from dictionaries before logging or auditing."""
    cleaned: dict[str, Any] = {}
    for k, v in data.items():
        if str(k).lower() in _SENSITIVE_KEYS:
            cleaned[k] = "[REDACTED]"
        elif isinstance(v, dict):
            cleaned[k] = scrub_dict(v)
        else:
            cleaned[k] = v
    return cleaned


class JsonFormatter(logging.Formatter):
    """Emit structured single-line JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        req_id = _request_id_var.get()
        if req_id:
            payload["request_id"] = req_id
        trace_id = _trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(scrub_dict(extra))
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", stream: Any = None) -> None:
    """Configure root logger for structured JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
