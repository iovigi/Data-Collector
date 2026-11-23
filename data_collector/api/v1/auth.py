"""Auth endpoints: login, refresh, logout, me."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import LoginRequest, RefreshRequest
from data_collector.domain.exceptions import BadRequestError

auth_bp = Blueprint("auth_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@auth_bp.post("/auth/login")
def login() -> ResponseReturnValue:
    dto = LoginRequest.model_validate(_json_body())
    container = get_container()
    result = container.auth_service.login(
        dto.email,
        dto.password,
        client_ip=request.remote_addr or "unknown",
    )
    return jsonify(result), 200


@auth_bp.post("/auth/refresh")
def refresh() -> ResponseReturnValue:
    dto = RefreshRequest.model_validate(_json_body())
    container = get_container()
    result = container.auth_service.refresh(dto.refresh_token)
    return jsonify(result), 200


@auth_bp.post("/auth/logout")
def logout() -> ResponseReturnValue:
    dto = RefreshRequest.model_validate(_json_body())
    container = get_container()
    container.auth_service.logout(dto.refresh_token)
    return jsonify({"status": "logged_out"}), 200


@auth_bp.get("/me")
@require_auth(is_mutation=False)
def me() -> ResponseReturnValue:
    actor = get_current_actor()
    return jsonify(
        {
            "principal_id": actor.principal_id,
            "principal_type": actor.principal_type.value,
            "email": actor.email,
            "workspace_id": actor.workspace_id,
            "scopes": sorted(s.value for s in actor.scopes) if actor.scopes is not None else None,
        }
    ), 200
