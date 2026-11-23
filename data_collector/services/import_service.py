"""Async/queued import service for JSON, JSONL/NDJSON, and CSV."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from data_collector.config import Settings
from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import require_workspace_membership
from data_collector.infrastructure.crypto import hash_token
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import (
    IdempotencyRepository,
    JobRepository,
    WorkspaceRepository,
)
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.record_service import _validate_against_collection_schema

ALLOWED_IMPORT_FORMATS = frozenset({"json", "jsonl", "ndjson", "csv"})


def parse_import_rows(raw_bytes: bytes, fmt: str) -> list[dict[str, Any]]:
    """Parse JSON, JSONL/NDJSON, or CSV bytes into a list of row dicts."""
    fmt = fmt.lower()
    if fmt not in ALLOWED_IMPORT_FORMATS:
        raise ValidationError(f"Unsupported import format '{fmt}'")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Import payload must be valid UTF-8 text") from exc

    if fmt == "json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Malformed JSON import: {exc.msg}") from exc
        if not isinstance(parsed, list):
            raise ValidationError("JSON import must be an array of objects")
        return [r if isinstance(r, dict) else {"__invalid__": r} for r in parsed]

    if fmt in {"jsonl", "ndjson"}:
        rows: list[dict[str, Any]] = []
        for idx, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                rows.append({"__parse_error__": f"Line {idx}: {exc.msg}"})
                continue
            rows.append(
                obj
                if isinstance(obj, dict)
                else {"__parse_error__": f"Line {idx}: expected object"}
            )
        return rows

    # CSV
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    return [dict(row) for row in reader]


class ImportService:
    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: WorkspaceRepository,
        collections: CollectionService,
        records: RecordRepository,
        jobs: JobRepository,
        idempotency: IdempotencyRepository,
        audit: AuditService,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._collections = collections
        self._records = records
        self._jobs = jobs
        self._idempotency = idempotency
        self._audit = audit

    def submit_import(
        self,
        actor: Actor,
        collection_id: str,
        *,
        raw_bytes: bytes,
        fmt: str,
        dry_run: bool = False,
        idempotency_key: str | None = None,
        rq_queue: Any | None = None,
    ) -> dict[str, Any]:
        if len(raw_bytes) > self._settings.max_import_bytes:
            raise PayloadTooLargeError("Import payload exceeds maximum allowed size")
        fmt = fmt.lower()
        if fmt not in ALLOWED_IMPORT_FORMATS:
            raise ValidationError(f"Unsupported import format '{fmt}'")

        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.JOBS_CREATE
        )
        ws_id = col["workspace_id"]

        if idempotency_key:
            key_hash = hash_token(idempotency_key)
            digest = hashlib.sha256(raw_bytes + fmt.encode("utf-8")).hexdigest()
            existing = self._idempotency.get(f"{ws_id}:{collection_id}", "POST", "import", key_hash)
            if existing is not None:
                if existing["request_digest"] != digest:
                    raise ConflictError("Idempotency-Key reused with different import payload")
                return dict(existing["response_body"])

        storage_root = Path(self._settings.storage_dir) / ws_id / "imports"
        storage_root.mkdir(parents=True, exist_ok=True)
        job = self._jobs.create(
            workspace_id=ws_id,
            initiator_id=actor.principal_id,
            job_type="import",
            params={
                "collection_id": collection_id,
                "project_id": col["project_id"],
                "format": fmt,
                "dry_run": dry_run,
            },
        )
        input_path = storage_root / f"{job['id']}.{fmt}"
        input_path.write_bytes(raw_bytes)
        self._jobs.update_state(
            job["id"],
            "queued",
            output_ref={"input_path": str(input_path)},
        )

        if idempotency_key:
            self._idempotency.save(
                scope=f"{ws_id}:{collection_id}",
                method="POST",
                path="import",
                key_hash=key_hash,
                request_digest=digest,
                status_code=202,
                response_body=job,
            )

        self._audit.record(
            tenant=ws_id,
            actor_id=actor.principal_id,
            action="job.import_create",
            target=f"job:{job['id']}",
            decision="allow",
        )

        if rq_queue is not None:
            rq_queue.enqueue("data_collector.workers.jobs.run_import_job", job["id"])
        else:
            self.execute_import_job(job["id"])

        updated = self._jobs.get_by_id(job["id"])
        return updated or job

    def execute_import_job(self, job_id: str) -> dict[str, Any]:
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

        input_path = Path((job.get("output_ref") or {}).get("input_path", ""))
        if not input_path.exists():
            return self._jobs.update_state(  # type: ignore[return-value]
                job_id, "failed", error_summary="Import input file missing", finished_at=utc_now()
            )

        try:
            rows = parse_import_rows(input_path.read_bytes(), params["format"])
        except ValidationError as exc:
            return self._jobs.update_state(  # type: ignore[return-value]
                job_id, "failed", error_summary=exc.message, finished_at=utc_now()
            )

        schema_json = col.get("schema_json", {})
        dry_run = bool(params.get("dry_run", False))
        succeeded = 0
        failed = 0
        row_errors: list[dict[str, Any]] = []

        for idx, row in enumerate(rows, start=1):
            # Check cancellation checkpoint periodically
            if idx % 50 == 0:
                latest = self._jobs.get_by_id(job_id)
                if latest and latest["state"] == "cancelled":
                    return latest

            if "__parse_error__" in row or "__invalid__" in row:
                failed += 1
                row_errors.append(
                    {"row": idx, "error": row.get("__parse_error__", "Expected JSON object")}
                )
                continue

            try:
                _validate_against_collection_schema(schema_json, row)
                if not dry_run:
                    self._records.insert_one(
                        workspace_id=job["workspace_id"],
                        project_id=params["project_id"],
                        collection_id=collection_id,
                        data=row,
                        created_by=job["initiator_id"],
                        source={"type": "import", "job_id": job_id},
                    )
                succeeded += 1
            except Exception as exc:
                failed += 1
                row_errors.append({"row": idx, "error": str(exc)})

        final = self._jobs.update_state(
            job_id,
            "completed",
            progress={
                "processed": len(rows),
                "succeeded": succeeded,
                "failed": failed,
                "total": len(rows),
            },
            errors=row_errors,
            finished_at=utc_now(),
        )
        return final or job

    def get_job(self, actor: Actor, job_id: str) -> dict[str, Any]:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        role = self._workspaces.get_membership_role(job["workspace_id"], actor.principal_id)
        require_workspace_membership(actor, job["workspace_id"], role, Scope.JOBS_READ)
        return job

    def cancel_job(self, actor: Actor, job_id: str) -> dict[str, Any]:
        job = self.get_job(actor, job_id)
        role = self._workspaces.get_membership_role(job["workspace_id"], actor.principal_id)
        require_workspace_membership(actor, job["workspace_id"], role, Scope.JOBS_CREATE)
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        updated = self._jobs.update_state(job_id, "cancelled", finished_at=utc_now())
        return updated or job
