"""Project endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import CreateProjectRequest
from data_collector.domain.exceptions import BadRequestError

projects_bp = Blueprint("projects_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@projects_bp.post("/workspaces/<wid>/projects")
@require_auth(is_mutation=True)
def create_project(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = CreateProjectRequest.model_validate(_json_body())
    proj = get_container().collection_service.create_project(
        actor, wid, slug=dto.slug, name=dto.name
    )
    return jsonify(proj), 201


@projects_bp.get("/workspaces/<wid>/projects")
@require_auth(is_mutation=False)
def list_projects(wid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    items = get_container().collection_service.list_projects(actor, wid)
    return jsonify({"items": items}), 200
