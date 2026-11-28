"""Thread-safe in-memory SearchBackend for isolated testing and local dev."""

from __future__ import annotations

import html
import re
import threading
from typing import Any

from data_collector.infrastructure.search_backend import SearchHit, SearchQueryResult

_PHRASE_RE = re.compile(r'"([^"]+)"')
_WORD_RE = re.compile(r"\S+")


def _parse_terms(query: str) -> tuple[list[str], list[str]]:
    phrases = [p.strip().casefold() for p in _PHRASE_RE.findall(query) if p.strip()]
    remainder = _PHRASE_RE.sub(" ", query)
    tokens = [t.strip().casefold() for t in _WORD_RE.findall(remainder) if t.strip()]
    return phrases, tokens


class InMemorySearchBackend:
    """In-memory derived index supporting tenant filters, phrases, highlights, and cursors."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._indexes: dict[str, dict[str, dict[str, Any]]] = {}

    def is_ready(self) -> bool:
        return True

    def health(self) -> dict[str, Any]:
        with self._lock:
            total = sum(len(docs) for docs in self._indexes.values())
        return {"backend": self.backend_name, "ready": True, "indexed_docs": total}

    def ensure_index(self, index_name: str) -> None:
        with self._lock:
            self._indexes.setdefault(index_name, {})

    def upsert_batch(self, index_name: str, docs: list[dict[str, Any]]) -> int:
        with self._lock:
            bucket = self._indexes.setdefault(index_name, {})
            for doc in docs:
                bucket[str(doc["search_doc_id"])] = dict(doc)
        return len(docs)

    def delete_docs(self, index_name: str, doc_ids: list[str]) -> int:
        removed = 0
        with self._lock:
            bucket = self._indexes.get(index_name, {})
            for doc_id in doc_ids:
                if bucket.pop(doc_id, None) is not None:
                    removed += 1
        return removed

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
        phrases, tokens = _parse_terms(query)
        with self._lock:
            docs = list(self._indexes.get(index_name, {}).values())

        scored: list[SearchHit] = []
        for doc in docs:
            if (
                doc.get("workspace_id") != workspace_id
                or doc.get("project_id") != project_id
                or doc.get("collection_id") != collection_id
            ):
                continue
            if active_only and not doc.get("active", True):
                continue

            text_fields: dict[str, str] = doc.get("text_fields") or {}
            candidate_paths = [path for path in text_fields if not fields or path in fields]
            if not candidate_paths:
                continue

            score = 0.0
            highlights: list[dict[str, str]] = []
            matched_phrases = 0
            matched_tokens = 0

            for ph in phrases:
                for p in candidate_paths:
                    val = text_fields[p]
                    if ph in val.casefold():
                        matched_phrases += 1
                        score += 3.0
                        highlights.append({"path": p, "text": html.escape(val[:180])})
                        break

            for tok in tokens:
                for p in candidate_paths:
                    val = text_fields[p]
                    if tok in val.casefold():
                        matched_tokens += 1
                        score += 1.0
                        if len(highlights) < 5:
                            highlights.append({"path": p, "text": html.escape(val[:180])})
                        break

            if len(phrases) > 0 and matched_phrases < len(phrases):
                continue
            if matched_tokens < len(tokens):
                continue
            if not phrases and not tokens:
                continue
            scored.append(
                SearchHit(
                    source_id=str(doc["source_id"]),
                    score=score,
                    highlights=highlights,
                    source_version=doc.get("indexed_source_version"),
                )
            )

        if sort == "created_at_asc":
            scored.sort(key=lambda item: item.source_id)
        elif sort == "created_at_desc":
            scored.sort(key=lambda item: item.source_id, reverse=True)
        else:
            scored.sort(key=lambda item: (-item.score, item.source_id))

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        page = scored[offset : offset + limit]
        has_more = offset + limit < len(scored)
        next_cursor = str(offset + limit) if has_more else None
        return SearchQueryResult(
            hits=page,
            next_cursor=next_cursor,
            has_more=has_more,
            total_estimated=len(scored),
        )
