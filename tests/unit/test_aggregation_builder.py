"""Aggregation builder: allowed/refused inputs, caps, unknown handling, tenant-first pipeline."""

from __future__ import annotations

from typing import Any

import pytest
from data_collector.domain.exceptions import ValidationError
from data_collector.services.analytics_service import (
    MAX_AGG_LIMIT,
    AnalyticsService,
    build_aggregate_spec,
    coverage_stages,
    present_expr,
)

ALLOWED = {"region", "categories", "email", "rating", "city", "has_website", "dc_event"}


def spec(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "group_by": None,
        "metrics": None,
        "having": None,
        "sort": None,
        "limit": None,
        "allowed_fields": ALLOWED,
    }
    args.update(kw)
    return build_aggregate_spec(**args)


def test_defaults_to_count_sorted_desc():
    s = spec(group_by=["region"])
    group = next(st["$group"] for st in s["stages"] if "$group" in st)
    assert group["_id"] == {"g0": "$_g0"}
    assert group["count"] == {"$sum": 1}
    sort = next(st["$sort"] for st in s["stages"] if "$sort" in st)
    assert list(sort.items())[0] == ("count", -1)
    assert s["stages"][-1] == {"$limit": 101}


def test_group_fields_are_unwound_and_empty_string_is_unknown():
    s = spec(group_by=["categories"])
    stages = s["stages"]
    assert stages[0]["$addFields"]["_g0"]["$cond"][0] == {"$isArray": "$data.categories"}
    assert stages[1] == {"$unwind": {"path": "$_g0", "preserveNullAndEmptyArrays": True}}
    assert stages[2]["$addFields"]["_g0"]["$cond"][0] == {"$eq": ["$_g0", ""]}


def test_nested_dotted_path_under_allowed_property():
    s = spec(group_by=["dc_event.source"], metrics=[{"op": "max", "field": "dc_event.observed_at"}])
    assert s["metrics"][0]["as"] == "max_dc_event_observed_at"
    assert s["stages"][0]["$addFields"]["_g0"]["$cond"][1] == "$data.dc_event.source"


def test_all_metric_ops_compile():
    s = spec(
        group_by=["region"],
        metrics=[
            {"op": "count"},
            {"op": "count", "field": "email", "as": "with_email"},
            {"op": "fill_rate", "field": "email", "as": "share_email"},
            {"op": "count_distinct", "field": "city"},
            {"op": "sum", "field": "rating"},
            {"op": "avg", "field": "rating"},
            {"op": "min", "field": "rating"},
            {"op": "max", "field": "rating"},
            {"op": "p50", "field": "rating"},
        ],
    )
    group = next(st["$group"] for st in s["stages"] if "$group" in st)
    assert group["with_email"] == {"$sum": {"$cond": [present_expr("$data.email"), 1, 0]}}
    assert group["share_email"] == {"$avg": {"$cond": [present_expr("$data.email"), 1, 0]}}
    assert group["count_distinct_city"] == {"$addToSet": "$data.city"}
    assert group["p50_rating"] == {"$median": {"input": "$data.rating", "method": "approximate"}}
    post = next(
        st["$addFields"] for st in s["stages"] if "count_distinct_city" in st.get("$addFields", {})
    )
    assert post["count_distinct_city"] == {"$size": "$count_distinct_city"}


def test_having_and_sort_by_group_field():
    s = spec(
        group_by=["region", "city"],
        having=[{"metric": "count", "op": "gte", "value": 5}],
        sort=[{"by": "city", "direction": "asc"}],
        limit=20,
    )
    assert {"$match": {"count": {"$gte": 5}}} in s["stages"]
    sort = next(st["$sort"] for st in s["stages"] if "$sort" in st)
    assert sort == {"_id.g1": 1, "_id.g0": 1}
    assert s["stages"][-1] == {"$limit": 21}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"group_by": ["a", "b", "c", "d"]}, "at most 3"),
        ({"group_by": ["region", "region"]}, "unique"),
        ({"group_by": ["secret_field"]}, "allowlist"),
        ({"group_by": ["$where"]}, "disallowed"),
        ({"group_by": ["region.$gt"]}, "disallowed"),
        ({"group_by": ["__proto__"]}, "Forbidden"),
        ({"group_by": ["id"]}, "one group per record"),
        ({"metrics": [{"op": "$function", "field": "rating"}]}, "op must be one of"),
        ({"metrics": [{"op": "sum"}]}, "requires a field"),
        ({"metrics": [{"op": "avg", "field": "secret_field"}]}, "allowlist"),
        ({"metrics": [{"op": "count", "pipeline": [{"$out": "x"}]}]}, "Unknown metric keys"),
        ({"metrics": [{"op": "count", "as": "$bad"}]}, "Invalid metric alias"),
        ({"metrics": [{"op": "count"}, {"op": "count"}]}, "Duplicate"),
        ({"metrics": [{"op": "count"}] * 11}, "At most 10"),
        ({"having": [{"metric": "nope", "op": "gt", "value": 1}]}, "having.metric"),
        ({"having": [{"metric": "count", "op": "$where", "value": 1}]}, "having.op"),
        ({"having": [{"metric": "count", "op": "gt", "value": {"$gt": 1}}]}, "number"),
        ({"sort": [{"by": "secret_field"}]}, "sort.by"),
        ({"sort": [{"by": "count", "direction": "sideways"}]}, "direction"),
        ({"limit": MAX_AGG_LIMIT + 1}, "<= 500"),
        ({"limit": 0}, "positive"),
        ({"limit": True}, "positive"),
    ],
)
def test_refused_inputs(kwargs, message):
    with pytest.raises(ValidationError) as exc:
        spec(**kwargs)
    assert message in exc.value.message


def test_no_schema_allows_any_safe_field_but_still_blocks_operators():
    spec(group_by=["anything"], allowed_fields=None)
    with pytest.raises(ValidationError):
        spec(group_by=["$anything"], allowed_fields=None)


def test_coverage_counts_unknown_per_group_field():
    st = coverage_stages(["region", "categories"])[0]["$group"]
    assert st["matched"] == {"$sum": 1}
    assert st["u0"] == {"$sum": {"$cond": [present_expr("$data.region"), 0, 1]}}
    assert st["u1"] == {"$sum": {"$cond": [present_expr("$data.categories"), 0, 1]}}
    assert "min_created_at" in st and "max_created_at" in st


def test_present_expr_treats_missing_null_empty_as_unknown():
    expr = present_expr("$data.x")["$and"]
    assert {"$ne": [{"$ifNull": ["$data.x", None]}, None]} in expr
    assert {"$ne": ["$data.x", ""]} in expr
    assert {"$ne": ["$data.x", []]} in expr


class _Recorder:
    def __init__(self) -> None:
        self.pipelines: list[list[dict[str, Any]]] = []
        self.kwargs: list[dict[str, Any]] = []

    def aggregate(self, pipeline, **kwargs):
        self.pipelines.append(pipeline)
        self.kwargs.append(kwargs)
        return iter([])

    def count_documents(self, *_a, **_k):
        return 0


class _Collections:
    def get_collection(self, actor, collection_id, required_scope=None):
        return {
            "id": collection_id,
            "workspace_id": "ws-A",
            "project_id": "p-A",
            "schema_json": {"properties": {k: {} for k in ALLOWED}},
            "searchable_fields": [],
        }


class _Settings:
    analytics_max_time_ms = 1234


class _Db:
    def __init__(self, rec):
        self.records = rec


def test_service_puts_tenant_scope_first_and_applies_budgets():
    rec = _Recorder()
    svc = AnalyticsService(settings=_Settings(), db=_Db(rec), collections=_Collections())  # type: ignore[arg-type]
    # A caller filter that names workspace_id is just a data field; it cannot widen scope.
    svc.aggregate(
        None,  # type: ignore[arg-type]
        "c-A",
        group_by=["region"],
        filter_ast={"field": "region", "op": "eq", "value": "TX"},
    )
    svc.histogram(None, "c-A", date_field="dc_event.observed_at", interval="week")  # type: ignore[arg-type]
    svc.distinct_values(None, "c-A", field="region")  # type: ignore[arg-type]
    scope = {
        "workspace_id": "ws-A",
        "project_id": "p-A",
        "collection_id": "c-A",
        "deleted_at": None,
    }
    for pipeline in rec.pipelines:
        first = pipeline[0]["$match"]
        assert first == scope or first["$and"][0] == scope
    for kw in rec.kwargs:
        assert kw == {"maxTimeMS": 1234, "allowDiskUse": False}


def test_histogram_rejects_bad_interval_and_non_date_fields():
    svc = AnalyticsService(settings=_Settings(), db=_Db(_Recorder()), collections=_Collections())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        svc.histogram(None, "c-A", interval="hour")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        svc.histogram(None, "c-A", date_field="version")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        svc.histogram(None, "c-A", date_field="secret_field")  # type: ignore[arg-type]
