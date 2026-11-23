"""Fail-closed RQ job queue used when JOBS_ASYNC=true.

The API process only enqueues; the independent worker process (`dc-worker`) executes.
If Redis is unreachable the job is marked failed and the request fails with 503, so a job
is never left silently "queued" without a queue entry.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from data_collector.domain.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

QUEUE_NAME = "default"
JOB_TIMEOUT_SECONDS = 1800


class JobQueue:
    """Thin wrapper around an RQ Queue with fail-closed semantics."""

    def __init__(self, redis_client: Any, jobs_repo: Any) -> None:
        from rq import Queue

        self._queue = Queue(QUEUE_NAME, connection=redis_client)
        self._jobs = jobs_repo

    def enqueue(self, func_path: str, job_id: str) -> None:
        try:
            self._queue.enqueue(
                func_path,
                job_id,
                job_timeout=JOB_TIMEOUT_SECONDS,
                result_ttl=86400,
                failure_ttl=7 * 86400,
            )
        except Exception as exc:
            logger.error(
                "Job enqueue failed",
                extra={"extra_fields": {"job_id": job_id, "exc": type(exc).__name__}},
            )
            self._jobs.update_state(
                job_id,
                "failed",
                error_summary="Job queue unavailable; job was not started",
                finished_at=datetime.now(UTC),
            )
            raise ServiceUnavailableError(
                "Background job queue is unavailable", retry_after=10
            ) from exc
