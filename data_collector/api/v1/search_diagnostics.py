"""Admin-only sanitized search planner diagnostics endpoint."""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask.typing import ResponseReturnValue

from data_collector.api.middleware import get_container, get_current_actor, require_auth
from data_collector.api.schemas import SearchPlanRequest
from data_collector.domain.exceptions import BadRequestError
from data_collector.domain.identities import Scope
from data_collector.services.search_planner import plan_search

search_diagnostics_bp = Blueprint("search_diagnostics_v1", __name__)


@search_diagnostics_bp.post("/collections/<cid>/search/plan")
@require_auth(is_mutation=False)
def inspect_search_plan(cid: str) -> ResponseReturnValue:
    actor = get_current_actor()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise BadRequestError("JSON object body is required")
    dto = SearchPlanRequest.model_validate(body)
    c = get_container()
    col = c.collection_service.get_collection(actor, cid, required_scope=Scope.WORKSPACE_MANAGE)
    sort_list = [s.model_dump() for s in dto.sort] if dto.sort else None
    plan = plan_search(
        actor,
        col,
        dto.filter,
        sort_list,
        dto.fields,
        settings=c.settings,
        source_db=c.mongo.db,
        fulltext_ready=c.settings.fulltext_search_enabled and c.search_backend.is_ready(),
    )
    return jsonify(plan.to_dict()), 200
