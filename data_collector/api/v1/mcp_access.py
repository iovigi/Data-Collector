"""Admin endpoints for MCP connections: connection info + check, personal tokens, grants."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.domain.exceptions import BadRequestError

mcp_access_bp = Blueprint("mcp_access_v1", __name__)


class CreateMcpTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] | None = Field(default=None, max_length=8)
    expires_in_days: int = Field(default=90, ge=1, le=365)


@mcp_access_bp.get("/workspaces/<wid>/mcp/connection-info")
@require_auth(is_mutation=False)
def connection_info(wid: str) -> ResponseReturnValue:
    return jsonify(get_container().mcp_access.connection_info(get_current_actor(), wid)), 200


@mcp_access_bp.post("/workspaces/<wid>/mcp/connection-check")
@require_auth(is_mutation=True)  # makes outbound requests: throttled like a write
def connection_check(wid: str) -> ResponseReturnValue:
    return jsonify(get_container().mcp_access.connection_check(get_current_actor(), wid)), 200


@mcp_access_bp.get("/workspaces/<wid>/mcp/tokens")
@require_auth(is_mutation=False)
def list_tokens(wid: str) -> ResponseReturnValue:
    items = get_container().mcp_access.list_tokens(get_current_actor(), wid)
    return jsonify({"items": items}), 200


@mcp_access_bp.post("/workspaces/<wid>/mcp/tokens")
@require_auth(is_mutation=True)
def create_token(wid: str) -> ResponseReturnValue:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    dto = CreateMcpTokenRequest.model_validate(body)
    res = get_container().mcp_access.create_token(
        get_current_actor(),
        wid,
        name=dto.name,
        scopes=dto.scopes,
        expires_in_days=dto.expires_in_days,
    )
    return jsonify(res), 201


@mcp_access_bp.post("/workspaces/<wid>/mcp/tokens/<tid>/revoke")
@require_auth(is_mutation=True)
def revoke_token(wid: str, tid: str) -> ResponseReturnValue:
    get_container().mcp_access.revoke_token(get_current_actor(), wid, tid)
    return jsonify({"status": "revoked"}), 200


@mcp_access_bp.get("/workspaces/<wid>/mcp/grants")
@require_auth(is_mutation=False)
def list_grants(wid: str) -> ResponseReturnValue:
    items = get_container().mcp_access.list_grants(get_current_actor(), wid)
    return jsonify({"items": items}), 200


@mcp_access_bp.post("/workspaces/<wid>/mcp/grants/<gid>/revoke")
@require_auth(is_mutation=True)
def revoke_grant(wid: str, gid: str) -> ResponseReturnValue:
    get_container().mcp_access.revoke_grant(get_current_actor(), wid, gid)
    return jsonify({"status": "revoked"}), 200
