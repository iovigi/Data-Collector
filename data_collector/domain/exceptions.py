"""Domain exceptions mapped deterministically to HTTP and MCP error codes."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base error for all domain and service failures."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    mcp_code: str = "TEMPORARY_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.retry_after = retry_after


class AuthenticationError(DomainError):
    code = "UNAUTHENTICATED"
    http_status = 401
    mcp_code = "UNAUTHENTICATED"


class AuthorizationError(DomainError):
    code = "FORBIDDEN"
    http_status = 403
    mcp_code = "FORBIDDEN"


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    http_status = 404
    mcp_code = "NOT_FOUND"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    http_status = 422
    mcp_code = "INVALID_ARGUMENT"


class BadRequestError(DomainError):
    code = "BAD_REQUEST"
    http_status = 400
    mcp_code = "INVALID_ARGUMENT"


class ConflictError(DomainError):
    code = "CONFLICT"
    http_status = 409
    mcp_code = "CONFLICT"


class PayloadTooLargeError(DomainError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413
    mcp_code = "INVALID_ARGUMENT"


class RateLimitError(DomainError):
    code = "RATE_LIMITED"
    http_status = 429
    mcp_code = "RATE_LIMITED"


class ServiceUnavailableError(DomainError):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503
    mcp_code = "TEMPORARY_UNAVAILABLE"
