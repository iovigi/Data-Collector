"""Workspace endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import AddMemberRequest, CreateWorkspaceRequest
from data_collector.domain.exceptions import BadRequestError

workspaces_bp = Blueprint("workspaces_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@workspaces_bp.get("/workspaces")
@require_auth(is_mutation=False)
def list_workspaces() -> ResponseReturnValue:
    actor = get_current_actor()
    limit = min(int(request.args.get("limit", 25)), 100)
    cursor = request.args.get("cursor")
    items = get_container().collection_service.list_workspaces(actor, limit=limit, cursor=cursor)
    return jsonify({"items": items}), 200


@workspaces_bp.post("/workspaces")
@require_auth(is_mutation=True)
def create_workspace() -> ResponseReturnValue:
    actor = get_current_actor()
    dto = CreateWorkspaceRequest.model_validate(_json_body())
    ws = get_container().collection_service.create_workspace(actor, slug=dto.slug, name=dto.name)
    return jsonify(ws), 201


@workspaces_bp.get("/workspaces/<wid>")
@require_auth(is_mutation=False)
def get_workspace(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    ws = get_container().collection_service.get_workspace(actor, wid)
    return jsonify(ws), 200


@workspaces_bp.post("/workspaces/<wid>/members")
@require_auth(is_mutation=True)
def add_member(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = AddMemberRequest.model_validate(_json_body())
    get_container().collection_service.add_member(actor, wid, dto.principal_id, dto.role)
    return jsonify({"status": "updated"}), 200
