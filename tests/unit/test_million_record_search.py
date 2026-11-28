"""Unit tests for million-record safe search planner, DSL extensions, and doc extractor."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from bson import ObjectId
from data_collector.config import Settings
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.services.query_dsl import compile_filter, iter_filter_predicates
from data_collector.services.search_document_builder import build_search_document
from data_collector.services.search_planner import plan_search


def test_build_search_document_nested_bounds_and_redaction() -> None:
    oid = ObjectId()
    raw = {
        "_id": oid,
        "workspace_id": "ws1",
        "project_id": "p1",
        "collection_id": "c1",
        "version": 3,
        "updated_at": datetime(2026, 11, 28, 12, 0, tzinfo=UTC),
        "deleted_at": None,
        "data": {
            "details": {
                "address": {"city": "Sofia"},
                "api_key": "super-secret-do-not-index",
            },
            "tags": ["alpha", "beta", "gamma"],
            "orders": [{"product": {"name": "Sensor"}}, {"product": {"name": "Gateway"}}],
            "blob": "A" * 300,
            "huge_list": list(range(150)),
        },
    }
    snapshot = deepcopy(raw)
    doc = build_search_document(raw, max_array_items=10)

    # Source record must never be mutated.
    assert raw == snapshot
    assert doc.source_id == str(oid)
    assert doc.active is True
    assert doc.text_fields["details.address.city"] == "Sofia"
    assert doc.text_fields["tags[]"] == "alpha | beta | gamma"
    assert doc.text_fields["orders[].product.name"] == "Sensor | Gateway"
    assert "details.api_key" not in doc.text_fields
    assert "blob" not in doc.text_fields
    assert doc.extraction_truncated is True


def test_query_dsl_array_contains_and_between() -> None:
    node = {
        "and": [
            {"field": "tags", "op": "array_contains", "value": "urgent"},
            {"field": "score", "op": "between", "value": [10, 50]},
        ]
    }
    compiled = compile_filter(node, allowed_fields={"tags", "score"})
    assert compiled == {
        "$and": [
            {"data.tags": "urgent"},
            {"data.score": {"$gte": 10, "$lte": 50}},
        ]
    }
    preds = iter_filter_predicates(node)
    assert preds == [("tags", "array_contains", "urgent"), ("score", "between", [10, 50])]


def test_search_planner_blocks_broad_contains_and_unindexed_sort() -> None:
    cfg = Settings(app_env="test")
    actor = Actor(principal_id="u1", principal_type=PrincipalType.USER)
    col = {"id": "c1", "sortable_fields": ["priority"], "searchable_fields": ["title"]}

    # Broad contains blocked when external full-text is not ready
    p_contains = plan_search(
        actor,
        col,
        {"field": "title", "op": "contains", "value": "hello"},
        None,
        None,
        settings=cfg,
        fulltext_ready=False,
    )
    assert p_contains.mode == "rejected"
    assert "contains" in (p_contains.refusal_reason or "")

    # Redirected to external_fulltext when ready
    p_ft = plan_search(
        actor,
        col,
        {"field": "title", "op": "contains", "value": "hello"},
        None,
        None,
        settings=cfg,
        fulltext_ready=True,
    )
    assert p_ft.mode == "external_fulltext"

    # Unapproved sort field rejected
    p_bad_sort = plan_search(
        actor,
        col,
        None,
        [{"field": "unindexed_col", "direction": "asc"}],
        None,
        settings=cfg,
    )
    assert p_bad_sort.mode == "rejected"

    # Default created_at sort approved
    p_ok = plan_search(
        actor,
        col,
        {"field": "title", "op": "eq", "value": "hello"},
        [{"field": "created_at", "direction": "desc"}],
        None,
        settings=cfg,
    )
    assert p_ok.mode == "source_indexed"
