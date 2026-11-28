"""Abstract SearchBackend protocol for isolated external full-text search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    score: float
    highlights: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SearchQueryResult:
    hits: list[SearchHit]
    next_cursor: str | None = None
    has_more: bool = False
    total_estimated: int | None = None


class SearchBackend(Protocol):
    """Pluggable external full-text search engine interface."""

    backend_name: str

    def is_ready(self) -> bool: ...

    def health(self) -> dict[str, Any]: ...

    def ensure_index(self, index_name: str) -> None: ...

    def upsert_batch(self, index_name: str, docs: list[dict[str, Any]]) -> int: ...

    def delete_docs(self, index_name: str, doc_ids: list[str]) -> int: ...

    def search(
        self,
        index_name: str,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        query: str,
        fields: list[str] | None,
        active_only: bool,
        limit: int,
        cursor: str | None,
        sort: str,
    ) -> SearchQueryResult: ...
