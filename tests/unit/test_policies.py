"""100% branch tests for RBAC and tenant authorization policy engine."""

from __future__ import annotations

import pytest
from data_collector.domain.exceptions import AuthorizationError, NotFoundError
from data_collector.domain.identities import Actor, PrincipalType, Role, Scope
from data_collector.domain.policies import (
    effective_scopes,
    require_collection_policy,
    require_workspace_membership,
)


def test_viewer_cannot_write_or_delete():
    actor = Actor(principal_id="u1", principal_type=PrincipalType.USER)
    role = require_workspace_membership(actor, "ws1", "viewer", Scope.RECORDS_READ)
    assert role == Role.VIEWER
    with pytest.raises(AuthorizationError):
        require_workspace_membership(actor, "ws1", "viewer", Scope.RECORDS_WRITE)


def test_non_member_and_cross_workspace_key_get_404():
    user = Actor(principal_id="u1", principal_type=PrincipalType.USER)
    with pytest.raises(NotFoundError):
        require_workspace_membership(user, "ws1", None, Scope.WORKSPACE_READ)

    key_actor = Actor(
        principal_id="u1",
        principal_type=PrincipalType.API_KEY,
        workspace_id="ws1",
        scopes=frozenset({Scope.RECORDS_READ}),
    )
    with pytest.raises(NotFoundError):
        require_workspace_membership(key_actor, "ws2", "owner", Scope.RECORDS_READ)


def test_mcp_read_only_strips_mutations_even_for_owner():
    mcp_ro = Actor(
        principal_id="u1",
        principal_type=PrincipalType.OAUTH_CLIENT,
        is_mcp=True,
        mcp_allow_writes=False,
    )
    scopes = effective_scopes(mcp_ro, Role.OWNER)
    assert Scope.RECORDS_READ in scopes
    assert Scope.RECORDS_WRITE not in scopes
    assert Scope.RECORDS_DELETE not in scopes


def test_collection_allowlist_enforced():
    actor = Actor(principal_id="u1", principal_type=PrincipalType.API_KEY, workspace_id="ws1")
    require_collection_policy(
        actor,
        "ws1",
        "editor",
        Scope.RECORDS_READ,
        allowed_collection_ids=["c1"],
        collection_id="c1",
    )
    with pytest.raises(AuthorizationError):
        require_collection_policy(
            actor,
            "ws1",
            "editor",
            Scope.RECORDS_READ,
            allowed_collection_ids=["c1"],
            collection_id="c2",
        )
