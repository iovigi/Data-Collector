"""Audit trail service with automatic secret/PII scrubbing."""

from __future__ import annotations

from typing import Any

from data_collector.infrastructure.logging import get_request_id, scrub_dict
from data_collector.infrastructure.repositories.tenant_repo import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    def record(
        self,
        *,
        tenant: str | None,
        actor_id: str,
        action: str,
        target: str,
        decision: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_meta = scrub_dict(metadata) if metadata else {}
        self._repo.append(
            tenant=tenant,
            actor_id=actor_id,
            action=action,
            target=target,
            decision=decision,
            request_id=get_request_id(),
            metadata=safe_meta,
        )

    def list_events(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._repo.list_by_tenant(workspace_id, limit=min(limit, 100))
