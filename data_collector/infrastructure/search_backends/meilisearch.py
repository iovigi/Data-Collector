"""Meilisearch HTTP SearchBackend with strict timeouts and tenant isolation."""

from __future__ import annotations

import html
from typing import Any

import httpx

from data_collector.domain.exceptions import SearchBackendUnavailableError
from data_collector.infrastructure.search_backend import SearchHit, SearchQueryResult


class MeilisearchBackend:
    backend_name = "meilisearch"

    def __init__(self, *, url: str, api_key: str = "", timeout_ms: int = 2000) -> None:
        self._base_url = url.rstrip("/")
        self._timeout = max(0.1, timeout_ms / 1000.0)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(base_url=self._base_url, headers=headers, timeout=self._timeout)

    def is_ready(self) -> bool:
        if not self._base_url:
            return False
        try:
            resp = self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "ready": self.is_ready()}

    def ensure_index(self, index_name: str) -> None:
        if not self._base_url:
            raise SearchBackendUnavailableError("FULLTEXT_SEARCH_URL is not configured")
        try:
            self._client.post("/indexes", json={"uid": index_name, "primaryKey": "search_doc_id"})
            self._client.put(
                f"/indexes/{index_name}/settings/filterable-attributes",
                json=["workspace_id", "project_id", "collection_id", "active"],
            )
            self._client.put(
                f"/indexes/{index_name}/settings/sortable-attributes",
                json=["source_updated_at", "source_id"],
            )
        except Exception as exc:
            raise SearchBackendUnavailableError(
                f"Meilisearch ensure_index failed: {type(exc).__name__}"
            ) from exc

    def upsert_batch(self, index_name: str, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        try:
            resp = self._client.post(f"/indexes/{index_name}/documents", json=docs)
            resp.raise_for_status()
            return len(docs)
        except Exception as exc:
            raise SearchBackendUnavailableError(
                f"Meilisearch upsert failed: {type(exc).__name__}"
            ) from exc

    def delete_docs(self, index_name: str, doc_ids: list[str]) -> int:
        if not doc_ids:
            return 0
        try:
            resp = self._client.post(
                f"/indexes/{index_name}/documents/delete-batch", json=doc_ids
            )
            resp.raise_for_status()
            return len(doc_ids)
        except Exception as exc:
            raise SearchBackendUnavailableError(
                f"Meilisearch delete failed: {type(exc).__name__}"
            ) from exc

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
        filters = [
            f'workspace_id = "{workspace_id}"',
            f'project_id = "{project_id}"',
            f'collection_id = "{collection_id}"',
        ]
        if active_only:
            filters.append("active = true")

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        payload: dict[str, Any] = {
            "q": query,
            "filter": " AND ".join(filters),
            "limit": limit,
            "offset": offset,
            "showRankingScore": True,
        }
        if fields:
            payload["attributesToSearchOn"] = [f"text_fields.{f}" for f in fields]
        if sort == "created_at_asc":
            payload["sort"] = ["source_id:asc"]
        elif sort == "created_at_desc":
            payload["sort"] = ["source_id:desc"]

        try:
            resp = self._client.post(f"/indexes/{index_name}/search", json=payload)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            raise SearchBackendUnavailableError(
                f"Meilisearch query failed: {type(exc).__name__}"
            ) from exc

        raw_hits = body.get("hits") or []
        hits: list[SearchHit] = []
        for h in raw_hits:
            snippet = str(h.get("display_snippet") or "")
            hl = [{"path": "snippet", "text": html.escape(snippet[:180])}] if snippet else []
            hits.append(
                SearchHit(
                    source_id=str(h["source_id"]),
                    score=float(h.get("_rankingScore") or 1.0),
                    highlights=hl,
                )
            )
        has_more = len(hits) == limit
        next_cursor = str(offset + limit) if has_more else None
        return SearchQueryResult(
            hits=hits,
            next_cursor=next_cursor,
            has_more=has_more,
            total_estimated=body.get("estimatedTotalHits"),
        )
