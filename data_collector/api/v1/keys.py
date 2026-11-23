"""Scoped API key management endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import CreateApiKeyRequest
from data_collector.domain.exceptions import BadRequestError

keys_bp = Blueprint("keys_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@keys_bp.post("/keys")
@require_auth(is_mutation=True)
def create_key() -> ResponseReturnValue:
    actor = get_current_actor()
    dto = CreateApiKeyRequest.model_validate(_json_body())
    res = get_container().auth_service.create_api_key(
        actor,
        workspace_id=dto.workspace_id,
        name=dto.name,
        scopes=dto.scopes,
        allowed_collection_ids=dto.allowed_collection_ids,
        expires_in_days=dto.expires_in_days,
    )
    return jsonify(res), 201


@keys_bp.get("/keys")
@require_auth(is_mutation=False)
def list_keys() -> ResponseReturnValue:
    actor = get_current_actor()
    wid = request.args.get("workspace_id", "")
    if not wid:
        raise BadRequestError("workspace_id query parameter is required")
    items = get_container().auth_service.list_api_keys(actor, wid)
    return jsonify({"items": items}), 200


@keys_bp.post("/keys/<kid>/revoke")
@require_auth(is_mutation=True)
def revoke_key(kid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True) or {}
    wid = body.get("workspace_id") or request.args.get("workspace_id", "")
    if not wid:
        raise BadRequestError("workspace_id is required")
    res = get_container().auth_service.revoke_api_key(actor, wid, kid)
    return jsonify(res), 200
