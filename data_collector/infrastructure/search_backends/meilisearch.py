"""Meilisearch HTTP SearchBackend with bounded requests and tenant isolation."""

from __future__ import annotations

import html
import json
import time
from typing import Any

import httpx

from data_collector.domain.exceptions import SearchBackendUnavailableError, ValidationError
from data_collector.infrastructure.search_backend import SearchHit, SearchQueryResult

# Keep offset-based relevance paging within Meilisearch's default result window.
RESULT_WINDOW = 1000
_TASK_WAIT_SECONDS = 60
_TEXT_PREFIX = "text_fields."


class MeilisearchBackend:
    backend_name = "meilisearch"

    def __init__(self, *, url: str, api_key: str = "", timeout_ms: int = 2000) -> None:
        self._base_url = url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=max(0.1, timeout_ms / 1000.0),
        )

    def is_ready(self) -> bool:
        if not self._base_url:
            return False
        try:
            resp = self._client.get("/health")
            return resp.status_code == 200 and resp.json().get("status") == "available"
        except (httpx.HTTPError, ValueError):
            return False

    def health(self) -> dict[str, Any]:
        return {"backend": self.backend_name, "ready": self.is_ready()}

    def _wait_for_task(self, response: httpx.Response, *, allow_existing: bool = False) -> None:
        response.raise_for_status()
        task_id = response.json()["taskUid"]
        deadline = time.monotonic() + _TASK_WAIT_SECONDS
        while time.monotonic() < deadline:
            task_response = self._client.get(f"/tasks/{task_id}")
            task_response.raise_for_status()
            task = task_response.json()
            status = task["status"]
            if status == "succeeded":
                return
            if status in {"failed", "canceled"}:
                error_code = (task.get("error") or {}).get("code") or status
                if allow_existing and error_code == "index_already_exists":
                    return
                raise SearchBackendUnavailableError(
                    f"Meilisearch indexing task {task_id} failed ({error_code})"
                )
            time.sleep(0.1)
        raise SearchBackendUnavailableError(f"Meilisearch indexing task {task_id} timed out")

    def ensure_index(self, index_name: str) -> None:
        if not self._base_url:
            raise SearchBackendUnavailableError("FULLTEXT_SEARCH_URL is not configured")
        index_url = f"/indexes/{index_name}"
        try:
            index = self._client.get(index_url)
            if index.status_code == 404:
                self._wait_for_task(
                    self._client.post(
                        "/indexes", json={"uid": index_name, "primaryKey": "search_doc_id"}
                    ),
                    allow_existing=True,
                )
                index = self._client.get(index_url)
            index.raise_for_status()
            if index.json().get("primaryKey") != "search_doc_id":
                raise SearchBackendUnavailableError(
                    "Meilisearch index has an unexpected primary key"
                )

            response = self._client.get(f"{index_url}/settings")
            response.raise_for_status()
            current = response.json()
            required = {
                "filterableAttributes": ["workspace_id", "project_id", "collection_id", "active"],
                "sortableAttributes": ["source_updated_at", "source_id"],
            }
            changes: dict[str, Any] = {}
            for key, attributes in required.items():
                configured = current.get(key) or []
                missing = [attribute for attribute in attributes if attribute not in configured]
                if missing:
                    changes[key] = [*configured, *missing]
            if current.get("searchableAttributes") != ["text_fields"]:
                changes["searchableAttributes"] = ["text_fields"]
            if changes:
                self._wait_for_task(self._client.patch(f"{index_url}/settings", json=changes))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SearchBackendUnavailableError(
                "Meilisearch could not prepare the external search index"
            ) from exc

    def upsert_batch(self, index_name: str, docs: list[dict[str, Any]]) -> int:
        if not docs:
            return 0
        try:
            self._wait_for_task(self._client.post(f"/indexes/{index_name}/documents", json=docs))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SearchBackendUnavailableError("Meilisearch could not index the batch") from exc
        return len(docs)

    def delete_docs(self, index_name: str, doc_ids: list[str]) -> int:
        if not doc_ids:
            return 0
        try:
            self._wait_for_task(
                self._client.post(f"/indexes/{index_name}/documents/delete-batch", json=doc_ids)
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SearchBackendUnavailableError("Meilisearch could not remove the batch") from exc
        return len(doc_ids)

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
            f"workspace_id = {json.dumps(workspace_id)}",
            f"project_id = {json.dumps(project_id)}",
            f"collection_id = {json.dumps(collection_id)}",
        ]
        if active_only:
            filters.append("active = true")

        offset = int(cursor) if cursor is not None else 0
        if not 0 <= offset < RESULT_WINDOW:
            raise ValidationError("Full-text cursor exceeds the result window")
        payload: dict[str, Any] = {
            "q": query,
            "filter": " AND ".join(filters),
            "limit": min(limit + 1, RESULT_WINDOW - offset),
            "offset": offset,
            "matchingStrategy": "all",
            "attributesToRetrieve": ["source_id", "indexed_source_version", "text_fields"],
            "showMatchesPosition": True,
            "showRankingScore": True,
        }
        if fields:
            payload["attributesToSearchOn"] = [f"{_TEXT_PREFIX}{field}" for field in fields]
        if sort == "created_at_asc":
            payload["sort"] = ["source_id:asc"]
        elif sort == "created_at_desc":
            payload["sort"] = ["source_id:desc"]

        try:
            resp = self._client.post(f"/indexes/{index_name}/search", json=payload)
            if (
                resp.status_code == 400
                and resp.json().get("code") == "invalid_search_attributes_to_search_on"
            ):
                raise ValidationError("Full-text fields must be exact indexed paths")
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchBackendUnavailableError(
                "Meilisearch could not complete the search"
            ) from exc

        raw_hits = body.get("hits") or []
        hits = [
            SearchHit(
                source_id=str(hit["source_id"]),
                score=float(hit.get("_rankingScore", 1.0)),
                highlights=_highlights(hit),
                source_version=hit.get("indexed_source_version"),
            )
            for hit in raw_hits[:limit]
            # Older external indexes may still match IDs or other index metadata.
            if any(path.startswith(_TEXT_PREFIX) for path in (hit.get("_matchesPosition") or {}))
        ]
        has_more = len(raw_hits) > limit
        return SearchQueryResult(
            hits=hits,
            next_cursor=str(offset + limit) if has_more else None,
            has_more=has_more,
            total_estimated=body.get("estimatedTotalHits"),
            result_window_limited=offset + min(len(raw_hits), limit) >= RESULT_WINDOW,
        )


def _highlights(hit: dict[str, Any]) -> list[dict[str, str]]:
    """Return short excerpts around real text matches, using Meilisearch's byte offsets."""
    fields = hit.get("text_fields") or {}
    excerpts: list[dict[str, str]] = []
    for attribute, matches in (hit.get("_matchesPosition") or {}).items():
        if not attribute.startswith(_TEXT_PREFIX) or not matches:
            continue
        path = attribute.removeprefix(_TEXT_PREFIX)
        value = fields.get(path)
        if not isinstance(value, str):
            continue
        raw = value.encode("utf-8")
        start = max(0, matches[0]["start"] - 20)
        end = start + 180
        snippet = raw[start:end].decode("utf-8", errors="ignore").strip()
        excerpt = ("…" if start else "") + snippet + ("…" if end < len(raw) else "")
        excerpts.append({"path": path, "text": html.escape(excerpt)})
        if len(excerpts) == 3:
            break
    return excerpts
