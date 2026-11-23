"""Standardized error envelope and Flask error handlers (no raw exception leakage)."""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, Response, jsonify
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import HTTPException

from data_collector.domain.exceptions import DomainError
from data_collector.infrastructure.logging import get_request_id

logger = logging.getLogger(__name__)


def error_response(
    *,
    code: str,
    message: str,
    status: int,
    details: list[dict[str, Any]] | None = None,
    retry_after: int | None = None,
) -> Response:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": get_request_id() or "req_unknown",
        }
    }
    resp = jsonify(payload)
    resp.status_code = status
    if retry_after is not None:
        resp.headers["Retry-After"] = str(retry_after)
    return resp


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(DomainError)
    def _handle_domain_error(exc: DomainError) -> Response:
        return error_response(
            code=exc.code,
            message=exc.message,
            status=exc.http_status,
            details=exc.details,
            retry_after=exc.retry_after,
        )

    @app.errorhandler(PydanticValidationError)
    def _handle_pydantic_error(exc: PydanticValidationError) -> Response:
        details = [
            {"path": ".".join(str(p) for p in err["loc"]), "reason": err["msg"]}
            for err in exc.errors()
        ]
        return error_response(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            status=422,
            details=details,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc: HTTPException) -> Response:
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            415: "UNSUPPORTED_MEDIA_TYPE",
            429: "RATE_LIMITED",
        }
        status = exc.code or 500
        return error_response(
            code=code_map.get(status, "HTTP_ERROR"),
            message=exc.description or "Request error",
            status=status,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception) -> Response:
        logger.exception("Unhandled exception", extra={"extra_fields": {"exc": type(exc).__name__}})
        return error_response(
            code="INTERNAL_ERROR",
            message="An internal error occurred",
            status=500,
        )
