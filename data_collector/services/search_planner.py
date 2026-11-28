"""Read-only search query planner and safety gate for million-record collections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pymongo.database import Database

from data_collector.config import Settings
from data_collector.domain.identities import Actor
from data_collector.services.query_dsl import iter_filter_predicates

_DEFAULT_INDEXED_SORTS = frozenset({"created_at", "id"})


@dataclass(frozen=True)
class SearchPlan:
    """Sanitized execution plan for a structured or full-text search."""

    mode: str  # "source_indexed" | "external_fulltext" | "rejected"
    selected_index: str | None
    estimated_bound: str
    max_time_ms: int
    pagination_strategy: str
    refusal_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "selected_index": self.selected_index,
            "estimated_bound": self.estimated_bound,
            "max_time_ms": self.max_time_ms,
            "pagination_strategy": self.pagination_strategy,
            "refusal_reason": self.refusal_reason,
            "warnings": list(self.warnings),
        }


def inspect_source_record_indexes(source_db: Database[Any]) -> list[str]:
    """Read-only inspection of existing index names/keys on `records`."""
    try:
        indexes = list(source_db.records.list_indexes())
    except Exception:
        return []
    names: list[str] = []
    for idx in indexes:
        keys = idx.get("key")
        if keys:
            key_names = (
                list(keys.keys()) if hasattr(keys, "keys") else [k for k, _ in keys]
            )
            names.append(",".join(key_names))
    return names


def plan_search(
    actor: Actor,
    collection: dict[str, Any],
    normalized_filter: dict[str, Any] | None,
    sort: list[dict[str, str]] | None,
    requested_fields: list[str] | None,
    *,
    settings: Settings,
    source_db: Database[Any] | None = None,
    fulltext_ready: bool = False,
) -> SearchPlan:
    """Plan a structured or external full-text search without touching source data."""
    _ = actor
    _ = requested_fields
    warnings: list[str] = []
    available_indexes = inspect_source_record_indexes(source_db) if source_db is not None else []
    has_scope_created_idx = any(
        idx.startswith("workspace_id,project_id,collection_id,deleted_at,created_at")
        for idx in available_indexes
    )
    has_scope_id_idx = any(
        idx.startswith("workspace_id,project_id,collection_id,deleted_at,_id")
        for idx in available_indexes
    )

    if source_db is not None and not (has_scope_created_idx or has_scope_id_idx):
        return SearchPlan(
            mode="rejected",
            selected_index=None,
            estimated_bound="unbounded",
            max_time_ms=settings.structured_search_max_time_ms,
            pagination_strategy="keyset",
            refusal_reason="Source collection lacks required tenant-scoped compound index",
        )

    predicates = iter_filter_predicates(normalized_filter)
    has_contains = any(op == "contains" for _, op, _ in predicates)
    if has_contains and settings.structured_search_block_broad_contains:
        if fulltext_ready:
            return SearchPlan(
                mode="external_fulltext",
                selected_index=settings.search_external_auxiliary_namespace,
                estimated_bound="external_index",
                max_time_ms=settings.fulltext_search_timeout_ms,
                pagination_strategy="search_cursor",
                warnings=[
                    "Broad 'contains' queries should use the external full-text endpoint."
                ],
            )
        return SearchPlan(
            mode="rejected",
            selected_index=None,
            estimated_bound="unbounded_regex_scan",
            max_time_ms=settings.structured_search_max_time_ms,
            pagination_strategy="keyset",
            refusal_reason=(
                "Broad 'contains' regex queries are blocked to prevent source collection scans; "
                "use exact/range filters or external full-text search."
            ),
        )

    sort_field = "created_at"
    if sort:
        sort_field = str(sort[0].get("field") or "created_at")
    sortable = set(collection.get("sortable_fields") or [])
    searchable = set(collection.get("searchable_fields") or [])
    approved_sorts = sortable | searchable
    if (
        sort_field not in _DEFAULT_INDEXED_SORTS
        and sort_field not in approved_sorts
        and not settings.structured_search_allow_unindexed
    ):
        return SearchPlan(
            mode="rejected",
            selected_index=None,
            estimated_bound="unindexed_sort",
            max_time_ms=settings.structured_search_max_time_ms,
            pagination_strategy="keyset",
            refusal_reason=(
                f"Sort field '{sort_field}' is not in approved sortable_fields or default "
                "indexed sort fields (created_at, id)."
            ),
        )

    selected_idx = (
        "workspace_id_1_project_id_1_collection_id_1_deleted_at_1_created_at_-1__id_-1"
        if sort_field == "created_at"
        else "workspace_id_1_project_id_1_collection_id_1_deleted_at_1__id_1"
    )
    if sort_field not in _DEFAULT_INDEXED_SORTS:
        warnings.append(
            f"Sort on '{sort_field}' relies on collection sortable_fields metadata."
        )

    return SearchPlan(
        mode="source_indexed",
        selected_index=selected_idx,
        estimated_bound="tenant_prefix_keyset",
        max_time_ms=settings.structured_search_max_time_ms,
        pagination_strategy="keyset",
        warnings=warnings,
    )
