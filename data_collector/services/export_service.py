"""Streaming full-data export service with ArtifactStore and CSV formula sanitization."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from bson import ObjectId

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
from data_collector.infrastructure.storage import ArtifactStore
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import compile_filter
from data_collector.services.record_service import _allowed_fields_for_collection

ALLOWED_EXPORT_FORMATS = frozenset({"json", "jsonl", "csv"})
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_EXPORT_BATCH_SIZE = 500


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
        artifacts: ArtifactStore,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._collections = collections
        self._records = records
        self._jobs = jobs
        self._artifacts = artifacts
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

    def _iter_export_batches(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        mongo_filter: dict[str, Any],
    ) -> Any:
        last_oid: ObjectId | None = None
        while True:
            cursor_filter = {"_id": {"$gt": last_oid}} if last_oid is not None else None
            batch = self._records.find_page(
                workspace_id=workspace_id,
                project_id=project_id,
                collection_id=collection_id,
                mongo_filter=mongo_filter,
                sort_field="_id",
                sort_direction=1,
                limit=_EXPORT_BATCH_SIZE,
                cursor_filter=cursor_filter,
                max_time_ms=self._settings.max_query_time_ms,
            )
            if not batch:
                break
            yield batch
            last_oid = ObjectId(batch[-1]["id"])
            if len(batch) < _EXPORT_BATCH_SIZE:
                break

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
        fmt = params["format"]
        artifact_key = f"{job['workspace_id']}/exports/{job_id}.{fmt}"
        out_path = self._artifacts.open_write_stream(artifact_key)

        exported = 0
        csv_keys: list[str] | None = None

        with out_path.open("w", encoding="utf-8", newline="") as f:
            if fmt == "json":
                f.write("[")
                first = True
                for batch in self._iter_export_batches(
                    workspace_id=job["workspace_id"],
                    project_id=params["project_id"],
                    collection_id=collection_id,
                    mongo_filter=mongo_filter,
                ):
                    for r in batch:
                        if not first:
                            f.write(",")
                        f.write(json.dumps(r["data"], default=str))
                        first = False
                        exported += 1
                f.write("]")
            elif fmt == "jsonl":
                for batch in self._iter_export_batches(
                    workspace_id=job["workspace_id"],
                    project_id=params["project_id"],
                    collection_id=collection_id,
                    mongo_filter=mongo_filter,
                ):
                    for r in batch:
                        f.write(json.dumps({"id": r["id"], "data": r["data"]}, default=str) + "\n")
                        exported += 1
            else:
                schema_props = col.get("schema_json", {}).get("properties", {})
                if isinstance(schema_props, dict) and schema_props:
                    csv_keys = sorted(schema_props.keys())
                writer: csv.DictWriter[str] | None = None
                for batch in self._iter_export_batches(
                    workspace_id=job["workspace_id"],
                    project_id=params["project_id"],
                    collection_id=collection_id,
                    mongo_filter=mongo_filter,
                ):
                    if writer is None:
                        if csv_keys is None:
                            csv_keys = sorted({k for r in batch for k in r.get("data", {})})
                        writer = csv.DictWriter(
                            f, fieldnames=["id", *csv_keys], extrasaction="ignore"
                        )
                        writer.writeheader()
                    for r in batch:
                        row_dict = {"id": r["id"]}
                        for k in csv_keys or []:
                            row_dict[k] = sanitize_csv_cell(r.get("data", {}).get(k))
                        writer.writerow(row_dict)
                        exported += 1

        checksum, byte_count = self._artifacts.finalize_stream(out_path)
        final = self._jobs.update_state(
            job_id,
            "completed",
            progress={"processed": exported, "succeeded": exported, "failed": 0, "total": exported},
            output_ref={
                "artifact_key": artifact_key,
                "format": fmt,
                "sha256": checksum,
                "bytes": byte_count,
                "complete": True,
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
        key = ref.get("artifact_key")
        if key:
            path = self._artifacts.get_path(key)
        else:
            path = Path(ref["path"])
            if not path.exists():
                raise NotFoundError("Export artifact not found")
        return path, ref["format"], ref["sha256"]
