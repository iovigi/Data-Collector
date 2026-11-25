"""Read-only, bounded, tenant-isolated aggregations over one collection's records.

Shared by the REST analytics endpoints (admin Analytics page) and the MCP tools
(dc_aggregate, dc_distinct_values, dc_histogram, dc_describe_collection), so both
surfaces return the same numbers.

Safety model
- Tenant scope (workspace_id, project_id, collection_id, deleted_at=None) is always the
  first $match stage and comes from the authorized collection, never from arguments.
- Every caller-supplied field passes `validate_field_name` against the collection
  allowlist; filters go through the Safe Query DSL compiler. Callers never supply
  pipeline stages, operators or expressions: the pipeline is built here.
- Every query runs with maxTimeMS and allowDiskUse=False; exceeding either budget
  raises QueryTooBroadError with advice to narrow the query.
- A missing, null, empty-string or empty-array value is "unknown". It is grouped
  under null and counted in `coverage.unknown`; it is never coerced to false/0.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from pymongo.database import Database
from pymongo.errors import ExecutionTimeout, OperationFailure

from data_collector.config import Settings
from data_collector.domain.entities import serialize_value
from data_collector.domain.exceptions import QueryTooBroadError, ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import compile_filter, validate_field_name
from data_collector.services.record_service import _allowed_fields_for_collection

MAX_GROUP_BY = 3
MAX_METRICS = 10
MAX_AGG_LIMIT = 500
DEFAULT_AGG_LIMIT = 100
MAX_DISTINCT_LIMIT = 200
DEFAULT_DISTINCT_LIMIT = 50
MAX_HISTOGRAM_BUCKETS = 1000
DESCRIBE_SAMPLE_SIZE = 1000
DESCRIBE_MAX_DEPTH = 3
DESCRIBE_MAX_FIELDS = 200

METRIC_OPS = frozenset({"count", "count_distinct", "sum", "avg", "min", "max", "p50", "fill_rate"})
FIELD_REQUIRED_OPS = METRIC_OPS - {"count"}
HAVING_OPS = {"eq": "$eq", "ne": "$ne", "gt": "$gt", "gte": "$gte", "lt": "$lt", "lte": "$lte"}
INTERVAL_FORMATS = {"day": "%Y-%m-%d", "week": "%G-W%V", "month": "%Y-%m"}
_ALIAS_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_TOP_LEVEL_META = {"created_at", "updated_at", "version"}
# MongoDB error codes for memory/time exhaustion during aggregation.
_TOO_BROAD_CODES = {50, 292, 16945, 16819, 146, 262}

_TOO_BROAD_MSG = (
    "Query too broad: it exceeded the server's time or memory budget. Add a filter, "
    "group by fewer or lower-cardinality fields, or lower the limit."
)


def field_ref(field: str) -> str:
    """MongoDB expression path for a public field name (validated beforehand)."""
    if field == "id":
        return "$_id"
    if field in _TOP_LEVEL_META:
        return f"${field}"
    return f"$data.{field}"


def present_expr(ref: str) -> dict[str, Any]:
    """True when the value is not missing, null, "" or []."""
    return {
        "$and": [
            {"$ne": [{"$ifNull": [ref, None]}, None]},
            {"$ne": [ref, ""]},
            {"$ne": [ref, []]},
        ]
    }


def _check_limit(raw: Any, default: int, maximum: int, name: str = "limit") -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValidationError(f"{name} must be a positive integer")
    if raw > maximum:
        raise ValidationError(f"{name} must be <= {maximum}")
    return raw


def _metric_alias(op: str, field: str | None) -> str:
    if field is None:
        return "count"
    return f"{op}_{field.replace('.', '_')}"


def build_aggregate_spec(
    *,
    group_by: list[str] | None,
    metrics: list[dict[str, Any]] | None,
    having: list[dict[str, Any]] | None,
    sort: list[dict[str, Any]] | None,
    limit: int | None,
    allowed_fields: set[str] | None,
) -> dict[str, Any]:
    """Validate caller input and return the post-$match pipeline parts.

    Pure function (no I/O) so it is unit-testable without a database.
    """
    groups = list(group_by or [])
    if len(groups) > MAX_GROUP_BY:
        raise ValidationError(f"group_by accepts at most {MAX_GROUP_BY} fields")
    if len(set(groups)) != len(groups):
        raise ValidationError("group_by fields must be unique")
    for g in groups:
        validate_field_name(g, allowed_fields)
        if g == "id":
            raise ValidationError("Cannot group by id (one group per record)")

    raw_metrics = list(metrics or [{"op": "count"}])
    if not raw_metrics:
        raw_metrics = [{"op": "count"}]
    if len(raw_metrics) > MAX_METRICS:
        raise ValidationError(f"At most {MAX_METRICS} metrics per query")

    accumulators: dict[str, Any] = {}
    post_project: dict[str, Any] = {}
    metric_out: list[dict[str, Any]] = []
    for m in raw_metrics:
        if not isinstance(m, dict):
            raise ValidationError("Each metric must be an object {op, field?, as?}")
        extra = set(m) - {"op", "field", "as"}
        if extra:
            raise ValidationError(f"Unknown metric keys: {sorted(extra)}")
        op = m.get("op")
        if op not in METRIC_OPS:
            raise ValidationError(f"Metric op must be one of {sorted(METRIC_OPS)}")
        field = m.get("field")
        if field is not None:
            validate_field_name(field, allowed_fields)
        if op in FIELD_REQUIRED_OPS and field is None:
            raise ValidationError(f"Metric '{op}' requires a field")
        alias = m.get("as") or _metric_alias(op, field)
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
            raise ValidationError(f"Invalid metric alias '{alias}'")
        if alias in accumulators or alias.startswith("_"):
            raise ValidationError(f"Duplicate or reserved metric alias '{alias}'")

        if op == "count":
            acc: Any = (
                {"$sum": 1}
                if field is None
                else {"$sum": {"$cond": [present_expr(field_ref(field)), 1, 0]}}
            )
        elif op == "fill_rate":
            assert field is not None
            acc = {"$avg": {"$cond": [present_expr(field_ref(field)), 1, 0]}}
        elif op == "count_distinct":
            assert field is not None
            acc = {"$addToSet": field_ref(field)}
            post_project[alias] = {"$size": f"${alias}"}
        elif op == "p50":
            assert field is not None
            acc = {"$median": {"input": field_ref(field), "method": "approximate"}}
        else:
            assert field is not None
            acc = {f"${op}": field_ref(field)}
        accumulators[alias] = acc
        metric_out.append({"op": op, "field": field, "as": alias})

    aliases = list(accumulators)
    group_keys = {g: f"_id.g{i}" for i, g in enumerate(groups)}

    having_match: dict[str, Any] = {}
    for h in having or []:
        if not isinstance(h, dict) or set(h) - {"metric", "op", "value"}:
            raise ValidationError("Each having clause must be {metric, op, value}")
        metric = h.get("metric")
        if metric not in accumulators:
            raise ValidationError(f"having.metric must be one of {aliases}")
        hop = h.get("op")
        if hop not in HAVING_OPS:
            raise ValidationError(f"having.op must be one of {sorted(HAVING_OPS)}")
        value = h.get("value")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError("having.value must be a number")
        having_match.setdefault(metric, {})[HAVING_OPS[hop]] = value

    sort_spec: dict[str, int] = {}
    for s in sort or []:
        if not isinstance(s, dict) or set(s) - {"by", "direction"}:
            raise ValidationError("Each sort entry must be {by, direction}")
        by = s.get("by")
        direction = str(s.get("direction", "desc")).lower()
        if direction not in {"asc", "desc"}:
            raise ValidationError("sort direction must be 'asc' or 'desc'")
        if by in accumulators:
            key = str(by)
        elif by in group_keys:
            key = group_keys[str(by)]
        else:
            raise ValidationError(f"sort.by must be a metric alias {aliases} or group field")
        sort_spec[key] = 1 if direction == "asc" else -1
    if not sort_spec:
        sort_spec[aliases[0]] = -1
    for key in group_keys.values():  # deterministic tie-break
        sort_spec.setdefault(key, 1)

    page = _check_limit(limit, DEFAULT_AGG_LIMIT, MAX_AGG_LIMIT)

    stages: list[dict[str, Any]] = []
    for i, g in enumerate(groups):
        ref = field_ref(g)
        name = f"_g{i}"
        # Arrays are unwound (a record counts once per element); scalars become a
        # one-element array so $unwind is a no-op for them. Missing/null/[] -> null.
        stages.append({"$addFields": {name: {"$cond": [{"$isArray": ref}, ref, [ref]]}}})
        stages.append({"$unwind": {"path": f"${name}", "preserveNullAndEmptyArrays": True}})
        stages.append(
            {"$addFields": {name: {"$cond": [{"$eq": [f"${name}", ""]}, None, f"${name}"]}}}
        )
    group_id: Any = {f"g{i}": f"$_g{i}" for i in range(len(groups))} if groups else None
    stages.append({"$group": {"_id": group_id, **accumulators}})
    if post_project:
        stages.append({"$addFields": post_project})
    if having_match:
        stages.append({"$match": having_match})
    stages.append({"$sort": sort_spec})
    stages.append({"$limit": page + 1})

    return {
        "stages": stages,
        "groups": groups,
        "metrics": metric_out,
        "limit": page,
    }


def coverage_stages(groups: list[str]) -> list[dict[str, Any]]:
    """One-pass coverage: matched count, unknown per group field, created_at range."""
    acc: dict[str, Any] = {
        "_id": None,
        "matched": {"$sum": 1},
        "min_created_at": {"$min": "$created_at"},
        "max_created_at": {"$max": "$created_at"},
    }
    for i, g in enumerate(groups):
        acc[f"u{i}"] = {"$sum": {"$cond": [present_expr(field_ref(g)), 0, 1]}}
    return [{"$group": acc}]


def _date_expr(field: str) -> dict[str, Any] | str:
    ref = field_ref(field)
    if field in {"created_at", "updated_at"}:
        return ref
    return {
        "$switch": {
            "branches": [
                {"case": {"$eq": [{"$type": ref}, "date"]}, "then": ref},
                {
                    "case": {"$eq": [{"$type": ref}, "string"]},
                    "then": {
                        "$dateFromString": {"dateString": ref, "onError": None, "onNull": None}
                    },
                },
            ],
            "default": None,
        }
    }


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


class AnalyticsService:
    def __init__(
        self, *, settings: Settings, db: Database[Any], collections: CollectionService
    ) -> None:
        self._settings = settings
        self._records = db.records
        self._collections = collections

    # ── plumbing ──────────────────────────────────────────────────────────────
    def _scope(self, actor: Actor, collection_id: str) -> tuple[dict[str, Any], set[str] | None]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        base = {
            "workspace_id": col["workspace_id"],
            "project_id": col["project_id"],
            "collection_id": collection_id,
            "deleted_at": None,
        }
        return base, _allowed_fields_for_collection(col)

    def _match(
        self, base: dict[str, Any], filter_ast: dict[str, Any] | None, allowed: set[str] | None
    ) -> dict[str, Any]:
        compiled = compile_filter(filter_ast, allowed_fields=allowed)
        # Tenant scope is always the leading stage; the caller filter can only narrow it.
        return {"$match": {"$and": [base, compiled]} if compiled else base}

    def _run(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            cursor = self._records.aggregate(
                pipeline,
                maxTimeMS=self._settings.analytics_max_time_ms,
                allowDiskUse=False,
            )
            return list(cursor)
        except ExecutionTimeout as exc:
            raise QueryTooBroadError(_TOO_BROAD_MSG) from exc
        except OperationFailure as exc:
            if exc.code in _TOO_BROAD_CODES:
                raise QueryTooBroadError(_TOO_BROAD_MSG) from exc
            raise ValidationError(
                f"Aggregation rejected by the database (code {exc.code}); "
                "check field types and metric ops"
            ) from exc

    @staticmethod
    def _freshness(cov: dict[str, Any]) -> dict[str, Any]:
        return {
            "min_created_at": serialize_value(cov.get("min_created_at")),
            "max_created_at": serialize_value(cov.get("max_created_at")),
        }

    # ── aggregate ─────────────────────────────────────────────────────────────
    def aggregate(
        self,
        actor: Actor,
        collection_id: str,
        *,
        group_by: list[str] | None = None,
        metrics: list[dict[str, Any]] | None = None,
        filter_ast: dict[str, Any] | None = None,
        having: list[dict[str, Any]] | None = None,
        sort: list[dict[str, Any]] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        base, allowed = self._scope(actor, collection_id)
        spec = build_aggregate_spec(
            group_by=group_by,
            metrics=metrics,
            having=having,
            sort=sort,
            limit=limit,
            allowed_fields=allowed,
        )
        match = self._match(base, filter_ast, allowed)
        raw = self._run([match, *spec["stages"]])
        cov_rows = self._run([match, *coverage_stages(spec["groups"])])
        cov = cov_rows[0] if cov_rows else {"matched": 0}

        groups: list[str] = spec["groups"]
        rows: list[dict[str, Any]] = []
        for doc in raw[: spec["limit"]]:
            key = doc.get("_id") or {}
            group_vals = {g: serialize_value(key.get(f"g{i}")) for i, g in enumerate(groups)}
            row: dict[str, Any] = {"group": group_vals} if groups else {}
            for m in spec["metrics"]:
                row[m["as"]] = serialize_value(doc.get(m["as"]))
            unknown = [g for g, v in group_vals.items() if v is None]
            if unknown:
                row["unknown_fields"] = unknown
            rows.append(row)

        return {
            "collection_id": collection_id,
            "group_by": groups,
            "metrics": spec["metrics"],
            "rows": rows,
            "truncated": len(raw) > spec["limit"],
            "coverage": {
                "matched": int(cov.get("matched", 0)),
                "unknown": {g: int(cov.get(f"u{i}", 0)) for i, g in enumerate(groups)},
                "freshness": self._freshness(cov),
            },
            "notes": [
                "Array fields in group_by are unwound: a record counts once per element.",
                "unknown = field missing, null, empty string or empty array.",
            ]
            if groups
            else [],
        }

    # ── distinct values ───────────────────────────────────────────────────────
    def distinct_values(
        self,
        actor: Actor,
        collection_id: str,
        *,
        field: str,
        filter_ast: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        page = _check_limit(limit, DEFAULT_DISTINCT_LIMIT, MAX_DISTINCT_LIMIT)
        res = self.aggregate(
            actor,
            collection_id,
            group_by=[field],
            metrics=[{"op": "count"}],
            filter_ast=filter_ast,
            sort=[{"by": "count", "direction": "desc"}],
            limit=page,
        )
        values = [
            {"value": r["group"][field], "count": r["count"]}
            for r in res["rows"]
            if r["group"][field] is not None
        ]
        return {
            "collection_id": collection_id,
            "field": field,
            "values": values,
            "truncated": res["truncated"],
            "coverage": res["coverage"],
        }

    # ── histogram ─────────────────────────────────────────────────────────────
    def histogram(
        self,
        actor: Actor,
        collection_id: str,
        *,
        date_field: str = "created_at",
        interval: str = "day",
        filter_ast: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if interval not in INTERVAL_FORMATS:
            raise ValidationError(f"interval must be one of {sorted(INTERVAL_FORMATS)}")
        base, allowed = self._scope(actor, collection_id)
        validate_field_name(date_field, allowed)
        if date_field in {"id", "version"}:
            raise ValidationError("date_field must be a date field")
        match = self._match(base, filter_ast, allowed)
        stages: list[dict[str, Any]] = [
            match,
            {"$project": {"_d": _date_expr(date_field)}},
            {
                "$group": {
                    "_id": {
                        "$cond": [
                            {"$eq": [{"$ifNull": ["$_d", None]}, None]},
                            None,
                            {
                                "$dateToString": {
                                    "format": INTERVAL_FORMATS[interval],
                                    "date": "$_d",
                                }
                            },
                        ]
                    },
                    "count": {"$sum": 1},
                    "min_d": {"$min": "$_d"},
                }
            },
            {"$sort": {"_id": 1}},
            {"$limit": MAX_HISTOGRAM_BUCKETS + 2},
        ]
        raw = self._run(stages)
        unknown = sum(int(r["count"]) for r in raw if r["_id"] is None)
        buckets = [
            {"bucket": r["_id"], "start": serialize_value(r.get("min_d")), "count": int(r["count"])}
            for r in raw
            if r["_id"] is not None
        ]
        truncated = len(buckets) > MAX_HISTOGRAM_BUCKETS
        buckets = buckets[:MAX_HISTOGRAM_BUCKETS]
        matched = sum(b["count"] for b in buckets) + unknown
        return {
            "collection_id": collection_id,
            "date_field": date_field,
            "interval": interval,
            "buckets": buckets,
            "truncated": truncated,
            "coverage": {"matched": matched, "unknown": {date_field: unknown}},
            "notes": ["Buckets are UTC. 'week' buckets are ISO weeks (YYYY-Www)."],
        }

    # ── field profile ─────────────────────────────────────────────────────────
    def describe_fields(self, actor: Actor, collection_id: str) -> dict[str, Any]:
        base, allowed = self._scope(actor, collection_id)
        total = int(self._records.count_documents(base))
        sample = self._run(
            [
                {"$match": base},
                {"$sample": {"size": DESCRIBE_SAMPLE_SIZE}},
                {"$project": {"data": 1}},
            ]
        )
        types: dict[str, Counter[str]] = {}
        present: Counter[str] = Counter()
        item_types: dict[str, Counter[str]] = {}

        def walk(obj: dict[str, Any], prefix: str, depth: int) -> None:
            for k, v in obj.items():
                if not isinstance(k, str) or k.startswith("$"):
                    continue
                path = f"{prefix}{k}"
                types.setdefault(path, Counter())[_type_name(v)] += 1
                if _is_present(v):
                    present[path] += 1
                if isinstance(v, list):
                    ic = item_types.setdefault(path, Counter())
                    for item in v[:20]:
                        ic[_type_name(item)] += 1
                if isinstance(v, dict) and depth < DESCRIBE_MAX_DEPTH:
                    walk(v, f"{path}.", depth + 1)

        for doc in sample:
            data = doc.get("data")
            if isinstance(data, dict):
                walk(data, "", 1)

        n = len(sample)
        fields: list[dict[str, Any]] = []
        for path, counter in types.items():
            try:
                validate_field_name(path, allowed)
                queryable = True
            except ValidationError:
                queryable = False
            dominant = counter.most_common(1)[0][0]
            entry: dict[str, Any] = {
                "field": path,
                "types": dict(counter),
                "fill_rate": round(present[path] / n, 4) if n else 0.0,
                "queryable": queryable,
                "groupable": queryable and dominant != "object",
            }
            if path in item_types and item_types[path]:
                entry["array_item_types"] = dict(item_types[path])
            fields.append(entry)
        fields.sort(key=lambda f: (-f["fill_rate"], f["field"]))
        truncated = len(fields) > DESCRIBE_MAX_FIELDS
        return {
            "collection_id": collection_id,
            "total_records": total,
            "sampled_records": n,
            "fields": fields[:DESCRIBE_MAX_FIELDS],
            "fields_truncated": truncated,
            "builtin_fields": ["created_at", "updated_at", "version", "id"],
        }
