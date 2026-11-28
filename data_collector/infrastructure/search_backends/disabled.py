"""Disabled SearchBackend implementation (safe default when full-text is off)."""

from __future__ import annotations

from typing import Any

from data_collector.domain.exceptions import SearchBackendUnavailableError
from data_collector.infrastructure.search_backend import SearchQueryResult


class DisabledSearchBackend:
    backend_name = "disabled"

    def is_ready(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "ready": False}

    def ensure_index(self, index_name: str) -> None:
        _ = index_name

    def upsert_batch(self, index_name: str, docs: list[dict[str, Any]]) -> int:
        _ = index_name, docs
        raise SearchBackendUnavailableError("External full-text search backend is disabled")

    def delete_docs(self, index_name: str, doc_ids: list[str]) -> int:
        _ = index_name, doc_ids
        raise SearchBackendUnavailableError("External full-text search backend is disabled")

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
    ) -> SearchQueryResult:
        _ = (
            index_name,
            workspace_id,
            project_id,
            collection_id,
            query,
            fields,
            active_only,
            limit,
            cursor,
            sort,
        )
        raise SearchBackendUnavailableError("External full-text search backend is disabled")
