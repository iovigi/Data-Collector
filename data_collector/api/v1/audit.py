"""Audit events endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.domain.exceptions import BadRequestError
from data_collector.domain.identities import Scope
from data_collector.domain.policies import require_workspace_membership

audit_bp = Blueprint("audit_v1", __name__)


@audit_bp.get("/audit")
@require_auth(is_mutation=False)
def list_audit() -> ResponseReturnValue:
    actor = get_current_actor()
    wid = request.args.get("workspace_id", "")
    if not wid:
        raise BadRequestError("workspace_id query parameter is required")
    container = get_container()
    role = container.workspaces.get_membership_role(wid, actor.principal_id)
    require_workspace_membership(actor, wid, role, Scope.AUDIT_READ)
    limit = min(int(request.args.get("limit", 50)), 100)
    events = container.audit_service.list_events(wid, limit=limit)
    return jsonify({"items": events}), 200
