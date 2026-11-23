"""Collection & schema registry endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import CreateCollectionRequest, UpdateCollectionRequest
from data_collector.domain.exceptions import BadRequestError

collections_bp = Blueprint("collections_v1", __name__)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    return body


@collections_bp.post("/projects/<pid>/collections")
@require_auth(is_mutation=True)
def create_collection(pid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = CreateCollectionRequest.model_validate(_json_body())
    col = get_container().collection_service.create_collection(
        actor,
        pid,
        slug=dto.slug,
        schema_json=dto.json_schema,
        searchable_fields=dto.searchable_fields,
        sortable_fields=dto.sortable_fields,
        retention_days=dto.retention_days,
    )
    return jsonify(col), 201


@collections_bp.get("/projects/<pid>/collections")
@require_auth(is_mutation=False)
def list_collections(pid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    items = get_container().collection_service.list_collections(actor, pid)
    return jsonify({"items": items}), 200


@collections_bp.get("/collections/<cid>")
@require_auth(is_mutation=False)
def get_collection(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    col = get_container().collection_service.get_collection(actor, cid)
    return jsonify(col), 200


@collections_bp.patch("/collections/<cid>")
@require_auth(is_mutation=True)
def update_collection(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    dto = UpdateCollectionRequest.model_validate(_json_body())
    col = get_container().collection_service.update_collection(
        actor,
        cid,
        schema_json=dto.json_schema,
        searchable_fields=dto.searchable_fields,
        sortable_fields=dto.sortable_fields,
        retention_days=dto.retention_days,
    )
    return jsonify(col), 200
