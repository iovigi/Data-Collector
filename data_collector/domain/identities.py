"""Principal and tenant identity models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrincipalType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    OAUTH_CLIENT = "oauth_client"


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class Scope(StrEnum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_MANAGE = "workspace:manage"
    COLLECTION_READ = "collection:read"
    COLLECTION_MANAGE = "collection:manage"
    RECORDS_READ = "records:read"
    RECORDS_WRITE = "records:write"
    RECORDS_DELETE = "records:delete"
    JOBS_READ = "jobs:read"
    JOBS_CREATE = "jobs:create"
    EXPORT_READ = "export:read"
    KEYS_MANAGE = "keys:manage"
    AUDIT_READ = "audit:read"


ALL_SCOPES: frozenset[Scope] = frozenset(Scope)

ROLE_SCOPES: dict[Role, frozenset[Scope]] = {
    Role.OWNER: ALL_SCOPES,
    Role.ADMIN: frozenset(
        {
            Scope.WORKSPACE_READ,
            Scope.COLLECTION_READ,
            Scope.COLLECTION_MANAGE,
            Scope.RECORDS_READ,
            Scope.RECORDS_WRITE,
            Scope.RECORDS_DELETE,
            Scope.JOBS_READ,
            Scope.JOBS_CREATE,
            Scope.EXPORT_READ,
            Scope.AUDIT_READ,
        }
    ),
    Role.EDITOR: frozenset(
        {
            Scope.WORKSPACE_READ,
            Scope.COLLECTION_READ,
            Scope.RECORDS_READ,
            Scope.RECORDS_WRITE,
            Scope.JOBS_READ,
            Scope.JOBS_CREATE,
            Scope.EXPORT_READ,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Scope.WORKSPACE_READ,
            Scope.COLLECTION_READ,
            Scope.RECORDS_READ,
            Scope.JOBS_READ,
            Scope.EXPORT_READ,
        }
    ),
}


@dataclass(frozen=True)
class Actor:
    """Authenticated caller context.

    Distinguishes user identity, workspace/key restriction, and OAuth/MCP client identity.
    """

    principal_id: str
    principal_type: PrincipalType
    email: str | None = None
    scopes: frozenset[Scope] | None = None  # None means inherit full role scopes
    workspace_id: str | None = None  # Set for workspace-scoped API keys
    client_id: str | None = None  # Set for OAuth / MCP clients
    key_id: str | None = None  # Set when authenticated via API key
    allowed_collection_ids: frozenset[str] | None = None  # Optional per-key collection allowlist
    is_mcp: bool = False
    mcp_allow_writes: bool = False
