"""Shared authorization policy engine (deny-by-default).

Used identically by Flask REST routes, background workers, and MCP tools.
"""

from __future__ import annotations

from data_collector.domain.exceptions import AuthorizationError, NotFoundError
from data_collector.domain.identities import ROLE_SCOPES, Actor, Role, Scope


def parse_role(raw_role: str) -> Role:
    """Convert raw role string to Role enum or raise AuthorizationError."""
    try:
        return Role(raw_role)
    except ValueError as exc:
        raise AuthorizationError("Invalid role assignment") from exc


def effective_scopes(actor: Actor, role: Role) -> frozenset[Scope]:
    """Compute effective scopes as intersection of role scopes and actor token/key scopes."""
    role_granted = ROLE_SCOPES.get(role, frozenset())
    granted = role_granted & actor.scopes if actor.scopes is not None else role_granted

    if actor.is_mcp and not actor.mcp_allow_writes:
        # Read-only MCP mode strips mutating scopes
        mutating = {
            Scope.WORKSPACE_MANAGE,
            Scope.COLLECTION_MANAGE,
            Scope.COLLECTION_DELETE,
            Scope.RECORDS_WRITE,
            Scope.RECORDS_DELETE,
            Scope.JOBS_CREATE,
            Scope.KEYS_MANAGE,
        }
        granted = granted - mutating

    return granted


def require_workspace_membership(
    actor: Actor,
    workspace_id: str,
    membership_role: str | None,
    required_scope: Scope,
) -> Role:
    """Verify actor is a member of workspace_id and holds required_scope.

    Returns 404 NotFoundError if actor has no membership or key is bound to another workspace
    to prevent cross-tenant resource existence leakage.
    """
    if actor.workspace_id is not None and actor.workspace_id != workspace_id:
        raise NotFoundError("Workspace not found")

    if not membership_role:
        raise NotFoundError("Workspace not found")

    role = parse_role(membership_role)
    scopes = effective_scopes(actor, role)
    if required_scope not in scopes:
        raise AuthorizationError(f"Missing required scope: {required_scope.value}")
    return role


def require_collection_policy(
    actor: Actor,
    workspace_id: str,
    membership_role: str | None,
    required_scope: Scope,
    allowed_collection_ids: list[str] | None = None,
    collection_id: str | None = None,
) -> Role:
    """Enforce workspace membership, scope, and optional per-key collection allowlist."""
    role = require_workspace_membership(actor, workspace_id, membership_role, required_scope)
    if (
        allowed_collection_ids is not None
        and collection_id is not None
        and collection_id not in allowed_collection_ids
    ):
        raise AuthorizationError("API key is not permitted for this collection")
    return role
