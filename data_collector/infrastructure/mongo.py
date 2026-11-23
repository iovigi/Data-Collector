"""Centralized MongoDB client lifecycle, pooling, and index management."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from data_collector.config import Settings


class MongoManager:
    """Manages a single pooled MongoClient per process."""

    def __init__(self, settings: Settings, client: MongoClient[Any] | None = None) -> None:
        self._settings = settings
        self._client: MongoClient[Any] = client or MongoClient(
            settings.mongodb_uri,
            maxPoolSize=settings.mongodb_max_pool_size,
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
            tz_aware=True,
        )
        self._db: Database[Any] = self._client[settings.mongodb_db]

    @property
    def client(self) -> MongoClient[Any]:
        return self._client

    @property
    def db(self) -> Database[Any]:
        return self._db

    def ping(self) -> bool:
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._client.close()

    def ensure_indexes(self) -> None:
        """Create mandatory internal and tenant-scoped compound indexes."""
        db = self._db
        db.users.create_index([("email", ASCENDING)], unique=True)
        db.workspaces.create_index([("slug", ASCENDING)], unique=True)
        db.memberships.create_index(
            [("workspace_id", ASCENDING), ("principal_id", ASCENDING)],
            unique=True,
        )
        db.projects.create_index(
            [("workspace_id", ASCENDING), ("slug", ASCENDING)],
            unique=True,
        )
        db.collections.create_index(
            [("project_id", ASCENDING), ("slug", ASCENDING)],
            unique=True,
        )
        db.api_keys.create_index([("prefix", ASCENDING)], unique=True)
        db.api_keys.create_index([("workspace_id", ASCENDING), ("principal_id", ASCENDING)])
        db.records.create_index(
            [
                ("workspace_id", ASCENDING),
                ("project_id", ASCENDING),
                ("collection_id", ASCENDING),
                ("deleted_at", ASCENDING),
                ("_id", ASCENDING),
            ]
        )
        db.records.create_index(
            [
                ("workspace_id", ASCENDING),
                ("project_id", ASCENDING),
                ("collection_id", ASCENDING),
                ("deleted_at", ASCENDING),
                ("created_at", DESCENDING),
                ("_id", DESCENDING),
            ]
        )
        db.jobs.create_index(
            [("workspace_id", ASCENDING), ("state", ASCENDING), ("created_at", DESCENDING)]
        )
        db.audit_events.create_index([("tenant", ASCENDING), ("timestamp", DESCENDING)])
        db.idempotency_keys.create_index(
            [
                ("scope", ASCENDING),
                ("method", ASCENDING),
                ("path", ASCENDING),
                ("key_hash", ASCENDING),
            ],
            unique=True,
        )
        db.idempotency_keys.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
        db.refresh_tokens.create_index([("token_hash", ASCENDING)], unique=True)
        db.refresh_tokens.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
        db.delete_intents.create_index([("jti", ASCENDING)], unique=True)
        db.delete_intents.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
