"""Async export service with CSV formula-injection sanitization and SHA-256 checksums."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from data_collector.config import Settings
from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import NotFoundError, ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import require_workspace_membership
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import (
    JobRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import compile_filter
from data_collector.services.record_service import _allowed_fields_for_collection

ALLOWED_EXPORT_FORMATS = frozenset({"json", "jsonl", "csv"})
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Prevent CSV formula injection (CWE-1236) by prefixing dangerous leading characters."""
    if value is None:
        return ""
    s = json.dumps(value) if isinstance(value, dict | list) else str(value)
    if s.startswith(_FORMULA_PREFIXES):
        return "'" + s
    return s


class ExportService:
    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: WorkspaceRepository,
        collections: CollectionService,
        records: RecordRepository,
        jobs: JobRepository,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._collections = collections
        self._records = records
        self._jobs = jobs
        self._audit = audit

    def submit_export(
        self,
        actor: Actor,
        collection_id: str,
        *,
        fmt: str = "jsonl",
        filter_ast: dict[str, Any] | None = None,
        rq_queue: Any | None = None,
    ) -> dict[str, Any]:
        fmt = fmt.lower()
        if fmt not in ALLOWED_EXPORT_FORMATS:
            raise ValidationError(f"Unsupported export format '{fmt}'")

        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.EXPORT_READ
        )
        ws_id = col["workspace_id"]
        allowed = _allowed_fields_for_collection(col)
        # Validate filter AST upfront before queuing
        compile_filter(filter_ast, allowed_fields=allowed)

        job = self._jobs.create(
            workspace_id=ws_id,
            initiator_id=actor.principal_id,
            job_type="export",
            params={
                "collection_id": collection_id,
                "project_id": col["project_id"],
                "format": fmt,
                "filter": filter_ast,
            },
        )
        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="job.export_create",
            target=f"job:{job['id']}",
            decision="allow",
        )

        if rq_queue is not None:
            rq_queue.enqueue("data_collector.workers.jobs.run_export_job", job["id"])
        else:
            self.execute_export_job(job["id"])

        return self._jobs.get_by_id(job["id"]) or job

    def execute_export_job(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        if job["state"] == "cancelled":
            return job

        self._jobs.update_state(job_id, "running", started_at=utc_now())
        params = job["params"]
        collection_id = params["collection_id"]
        col = self._collections._collections.get_by_id(collection_id)
        if col is None:
            return self._jobs.update_state(  # type: ignore[return-value]
                job_id, "failed", error_summary="Collection not found", finished_at=utc_now()
            )

        allowed = _allowed_fields_for_collection(col)
        mongo_filter = compile_filter(params.get("filter"), allowed_fields=allowed)
        rows = self._records.find_page(
            workspace_id=job["workspace_id"],
            project_id=params["project_id"],
            collection_id=collection_id,
            mongo_filter=mongo_filter,
            sort_field="_id",
            sort_direction=1,
            limit=10000,
            max_time_ms=self._settings.max_query_time_ms,
        )

        fmt = params["format"]
        out_dir = Path(self._settings.storage_dir) / job["workspace_id"] / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{job_id}.{fmt}"

        if fmt == "json":
            payload_bytes = json.dumps([r["data"] for r in rows], default=str).encode("utf-8")
        elif fmt == "jsonl":
            lines = [json.dumps({"id": r["id"], "data": r["data"]}, default=str) for r in rows]
            payload_bytes = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        else:
            buf = io.StringIO()
            keys = sorted({k for r in rows for k in r.get("data", {})})
            writer = csv.DictWriter(buf, fieldnames=["id", *keys])
            writer.writeheader()
            for r in rows:
                row_dict = {"id": r["id"]}
                for k in keys:
                    row_dict[k] = sanitize_csv_cell(r.get("data", {}).get(k))
                writer.writerow(row_dict)
            payload_bytes = buf.getvalue().encode("utf-8")

        out_path.write_bytes(payload_bytes)
        checksum = hashlib.sha256(payload_bytes).hexdigest()

        final = self._jobs.update_state(
            job_id,
            "completed",
            progress={
                "processed": len(rows),
                "succeeded": len(rows),
                "failed": 0,
                "total": len(rows),
            },
            output_ref={
                "path": str(out_path),
                "format": fmt,
                "sha256": checksum,
                "bytes": len(payload_bytes),
            },
            finished_at=utc_now(),
        )
        return final or job

    def get_export_result(self, actor: Actor, job_id: str) -> tuple[Path, str, str]:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        role = self._workspaces.get_membership_role(job["workspace_id"], actor.principal_id)
        require_workspace_membership(actor, job["workspace_id"], role, Scope.EXPORT_READ)
        if job["state"] != "completed" or not job.get("output_ref"):
            raise ValidationError("Export job has not completed")
        ref = job["output_ref"]
        path = Path(ref["path"])
        if not path.exists():
            raise NotFoundError("Export artifact not found")
        return path, ref["format"], ref["sha256"]
