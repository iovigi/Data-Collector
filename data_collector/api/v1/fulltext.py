"""External full-text search & status endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import FulltextSearchRequest
from data_collector.domain.exceptions import BadRequestError, ValidationError

fulltext_bp = Blueprint("fulltext_v1", __name__)


@fulltext_bp.post("/collections/<cid>/records/fulltext")
@require_auth(is_mutation=False)
def fulltext_search_records(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    dto = FulltextSearchRequest.model_validate(body)
    if dto.filter is not None or body.get("filters") is not None:
        raise ValidationError("Full-text search does not support structured filters")
    res = get_container().fulltext_search.search(
        actor,
        cid,
        query=dto.query,
        fields=dto.fields,
        limit=dto.limit,
        cursor=dto.cursor,
        sort=dto.sort,
    )
    return jsonify(res), 200


@fulltext_bp.get("/collections/<cid>/search/status")
@require_auth(is_mutation=False)
def get_collection_search_status(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    res = get_container().fulltext_search.get_status(actor, cid)
    return jsonify(res), 200
