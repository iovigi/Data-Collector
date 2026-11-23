"""Dependency injection container for API, worker, and MCP processes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient

from data_collector.config import Settings, get_settings
from data_collector.infrastructure.mongo import MongoManager
from data_collector.infrastructure.redis import RedisManager
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import (
    ApiKeyRepository,
    AuditRepository,
    CollectionRepository,
    DeleteIntentRepository,
    IdempotencyRepository,
    JobRepository,
    ProjectRepository,
    RefreshTokenRepository,
    UserRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService
from data_collector.services.auth_service import AuthService
from data_collector.services.collection_service import CollectionService
from data_collector.services.export_service import ExportService
from data_collector.services.import_service import ImportService
from data_collector.services.record_service import RecordService


@dataclass
class Container:
    settings: Settings
    mongo: MongoManager
    redis: RedisManager
    users: UserRepository
    workspaces: WorkspaceRepository
    projects: ProjectRepository
    collections: CollectionRepository
    api_keys: ApiKeyRepository
    refresh_tokens: RefreshTokenRepository
    audit_repo: AuditRepository
    idempotency: IdempotencyRepository
    jobs: JobRepository
    delete_intents: DeleteIntentRepository
    records: RecordRepository
    audit_service: AuditService
    auth_service: AuthService
    collection_service: CollectionService
    record_service: RecordService
    import_service: ImportService
    export_service: ExportService

    def close(self) -> None:
        self.mongo.close()
        self.redis.close()


def build_container(
    settings: Settings | None = None,
    *,
    mongo_client: MongoClient[Any] | None = None,
    redis_client: Any | None = None,
    ensure_indexes: bool = False,
) -> Container:
    """Build wired application container."""
    cfg = settings or get_settings()
    mongo = MongoManager(cfg, client=mongo_client)
    if ensure_indexes:
        mongo.ensure_indexes()
    redis_mgr = RedisManager(cfg, client=redis_client)

    db = mongo.db
    users = UserRepository(db)
    workspaces = WorkspaceRepository(db)
    projects = ProjectRepository(db)
    collections = CollectionRepository(db)
    api_keys = ApiKeyRepository(db)
    refresh_tokens = RefreshTokenRepository(db)
    audit_repo = AuditRepository(db)
    idempotency = IdempotencyRepository(db)
    jobs = JobRepository(db)
    delete_intents = DeleteIntentRepository(db)
    records = RecordRepository(db)

    audit_service = AuditService(audit_repo)
    auth_service = AuthService(
        settings=cfg,
        users=users,
        workspaces=workspaces,
        api_keys=api_keys,
        refresh_tokens=refresh_tokens,
        audit=audit_service,
        rate_limiter=redis_mgr.rate_limiter,
    )
    collection_service = CollectionService(
        workspaces=workspaces,
        projects=projects,
        collections=collections,
        audit=audit_service,
    )
    record_service = RecordService(
        settings=cfg,
        collections=collection_service,
        records=records,
        idempotency=idempotency,
        audit=audit_service,
    )
    import_service = ImportService(
        settings=cfg,
        workspaces=workspaces,
        collections=collection_service,
        records=records,
        jobs=jobs,
        idempotency=idempotency,
        audit=audit_service,
    )
    export_service = ExportService(
        settings=cfg,
        workspaces=workspaces,
        collections=collection_service,
        records=records,
        jobs=jobs,
        audit=audit_service,
    )

    return Container(
        settings=cfg,
        mongo=mongo,
        redis=redis_mgr,
        users=users,
        workspaces=workspaces,
        projects=projects,
        collections=collections,
        api_keys=api_keys,
        refresh_tokens=refresh_tokens,
        audit_repo=audit_repo,
        idempotency=idempotency,
        jobs=jobs,
        delete_intents=delete_intents,
        records=records,
        audit_service=audit_service,
        auth_service=auth_service,
        collection_service=collection_service,
        record_service=record_service,
        import_service=import_service,
        export_service=export_service,
    )
