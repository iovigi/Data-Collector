"""Synthetic benchmark for count cache, document extraction, and in-memory fulltext.

Runs exclusively against disposable in-memory/synthetic fixtures; never touches
a production MongoDB database.
"""

from __future__ import annotations

import os
import statistics
import time
from datetime import UTC, datetime

import fakeredis
import mongomock
from bson import ObjectId
from data_collector.app import create_app
from data_collector.config import Settings
from data_collector.domain.identities import Actor, PrincipalType
from data_collector.services.search_document_builder import build_search_document


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def main() -> None:
    cfg = Settings(
        app_env="test",
        jwt_secret_key=os.urandom(32).hex(),
        fulltext_search_enabled=True,
        fulltext_search_backend="memory",
        search_backfill_enabled=True,
    )
    app = create_app(
        cfg,
        mongo_client=mongomock.MongoClient(),
        redis_client=fakeredis.FakeRedis(),
        ensure_indexes=True,
    )
    c = app.extensions["container"]
    user = c.auth_service.register_user("bench@example.com", "VeryStrongPassword123!")
    actor = Actor(principal_id=user["id"], principal_type=PrincipalType.USER)
    ws = c.collection_service.create_workspace(actor, slug="bench-ws", name="Bench WS")
    proj = c.collection_service.create_project(actor, ws["id"], slug="bench-p", name="Bench P")
    col = c.collection_service.create_collection(
        actor,
        proj["id"],
        slug="events",
        schema_json={},
        searchable_fields=["status", "details"],
    )

    # Generate 2,000 nested synthetic records in disposable fixture
    total_docs = 2000
    raw_docs = [
        {
            "_id": ObjectId(),
            "workspace_id": ws["id"],
            "project_id": proj["id"],
            "collection_id": col["id"],
            "version": 1,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": user["id"],
            "deleted_at": None,
            "source": {"type": "bench"},
            "data": {
                "status": "failed" if i % 5 == 0 else "ok",
                "details": {
                    "address": {"city": "Sofia" if i % 2 == 0 else "Varna"},
                    "message": f"Event payload #{i} payment {'failed' if i % 5 == 0 else 'ok'}",
                },
                "tags": ["edge", f"batch-{i % 10}"],
            },
        }
        for i in range(total_docs)
    ]
    c.mongo.db.records.insert_many(raw_docs)

    # 1. Document extraction throughput
    t0 = time.perf_counter()
    for d in raw_docs:
        build_search_document(d)
    extract_ms = (time.perf_counter() - t0) * 1000.0

    # 2. Backfill throughput
    t_bf = time.perf_counter()
    c.search_indexer.backfill_collection(col["id"], batch_size=250, max_docs_per_second=10000)
    backfill_ms = (time.perf_counter() - t_bf) * 1000.0

    # 3. Warm count cache latency
    c.collection_counts.get_collection_count(actor, col["id"], refresh=True)
    count_latencies: list[float] = []
    for _ in range(50):
        s = time.perf_counter()
        c.collection_counts.get_batch_counts(actor, [col["id"]])
        count_latencies.append((time.perf_counter() - s) * 1000.0)

    # 4. Structured search latency
    struct_latencies: list[float] = []
    for _ in range(30):
        s = time.perf_counter()
        c.record_service.search_records(
            actor,
            col["id"],
            filter_ast={"field": "status", "op": "eq", "value": "failed"},
            limit=25,
        )
        struct_latencies.append((time.perf_counter() - s) * 1000.0)

    # 5. Full-text search + hydration latency
    ft_latencies: list[float] = []
    for _ in range(30):
        s = time.perf_counter()
        c.fulltext_search.search(actor, col["id"], query="payment failed", limit=25)
        ft_latencies.append((time.perf_counter() - s) * 1000.0)

    print(f"SYNTHETIC_DOCS={total_docs}")
    print(f"EXTRACT_MS={extract_ms:.2f}")
    print(f"BACKFILL_MS={backfill_ms:.2f}")
    print(
        f"COUNT_CACHE_MS p50={statistics.median(count_latencies):.3f} "
        f"p95={_percentile(count_latencies, 95):.3f} p99={_percentile(count_latencies, 99):.3f}"
    )
    print(
        f"STRUCTURED_SEARCH_MS p50={statistics.median(struct_latencies):.3f} "
        f"p95={_percentile(struct_latencies, 95):.3f} p99={_percentile(struct_latencies, 99):.3f}"
    )
    print(
        f"FULLTEXT_HYDRATE_MS p50={statistics.median(ft_latencies):.3f} "
        f"p95={_percentile(ft_latencies, 95):.3f} p99={_percentile(ft_latencies, 99):.3f}"
    )
    c.close()


if __name__ == "__main__":
    main()
