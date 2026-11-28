"""Factory for SearchBackend implementations."""

from __future__ import annotations

from data_collector.config import Settings
from data_collector.infrastructure.search_backend import SearchBackend
from data_collector.infrastructure.search_backends.disabled import DisabledSearchBackend
from data_collector.infrastructure.search_backends.meilisearch import MeilisearchBackend
from data_collector.infrastructure.search_backends.memory import InMemorySearchBackend


def build_search_backend(settings: Settings) -> SearchBackend:
    """Create the configured external SearchBackend without failing API startup."""
    if settings.fulltext_search_backend == "memory":
        return InMemorySearchBackend()
    if settings.fulltext_search_backend == "meilisearch":
        return MeilisearchBackend(
            url=settings.fulltext_search_url,
            api_key=settings.fulltext_search_api_key,
            timeout_ms=settings.fulltext_search_timeout_ms,
        )
    return DisabledSearchBackend()
