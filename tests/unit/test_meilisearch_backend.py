from __future__ import annotations

import json

import httpx
import pytest
from data_collector.domain.exceptions import SearchBackendUnavailableError
from data_collector.infrastructure.search_backends.meilisearch import MeilisearchBackend


def test_meilisearch_waits_for_indexing_task_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"taskUid": 7})
        return httpx.Response(200, json={"status": "failed", "error": {"code": "invalid_document"}})

    backend = MeilisearchBackend(url="http://meilisearch.test")
    with httpx.Client(
        base_url="http://meilisearch.test", transport=httpx.MockTransport(handler)
    ) as client:
        monkeypatch.setattr(backend, "_client", client)
        with pytest.raises(SearchBackendUnavailableError, match="invalid_document"):
            backend.upsert_batch("search", [{"search_doc_id": "abc"}])
    assert requests == ["/indexes/search/documents", "/tasks/7"]


def test_meilisearch_search_uses_lookahead_and_real_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "София " + "context " * 30 + "Payment failed <marker>"
    request_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "source_id": "first",
                        "indexed_source_version": 2,
                        "text_fields": {"details.message": text},
                        "_matchesPosition": {
                            "text_fields.details.message": [
                                {"start": text.encode().index(b"Payment"), "length": 7}
                            ]
                        },
                    }
                ]
            },
        )

    backend = MeilisearchBackend(url="http://meilisearch.test")
    with httpx.Client(
        base_url="http://meilisearch.test", transport=httpx.MockTransport(handler)
    ) as client:
        monkeypatch.setattr(backend, "_client", client)
        result = backend.search(
            "search",
            workspace_id="workspace",
            project_id="project",
            collection_id="collection",
            query='"Payment failed"',
            fields=None,
            active_only=True,
            limit=1,
            cursor=None,
            sort="relevance",
        )

    [payload] = request_payloads
    assert payload["limit"] == 2
    assert "attributesToSearchOn" not in payload
    assert 'collection_id = "collection" AND active = true' in payload["filter"]
    assert result.next_cursor is None
    assert not result.has_more
    [hit] = result.hits
    assert hit.source_version == 2
    assert hit.highlights == [
        {
            "path": "details.message",
            "text": "…ext context context Payment failed &lt;marker&gt;",
        }
    ]
